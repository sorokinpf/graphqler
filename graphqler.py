#!/usr/bin/env python


import json
import itertools
import string
import random
import pyjq
import requests
import re
import urllib3
import pandas as pd
import argparse
from copy import copy

urllib3.disable_warnings()

introspection_query = '{"operationName":"IntrospectionQuery","variables":{},"query":"    query IntrospectionQuery {\n      __schema {\n        queryType { name }\n        mutationType { name }\n        subscriptionType { name }\n        types {\n          ...FullType\n        }\n        directives {\n          name\n          description\n          locations\n          args {\n            ...InputValue\n          }\n        }\n      }\n    }\n\n    fragment FullType on __Type {\n      kind\n      name\n      description\n      fields(includeDeprecated: true) {\n        name\n        description\n        args {\n          ...InputValue\n        }\n        type {\n          ...TypeRef\n        }\n        isDeprecated\n        deprecationReason\n      }\n      inputFields {\n        ...InputValue\n      }\n      interfaces {\n        ...TypeRef\n      }\n      enumValues(includeDeprecated: true) {\n        name\n        description\n        isDeprecated\n        deprecationReason\n      }\n      possibleTypes {\n        ...TypeRef\n      }\n    }\n\n    fragment InputValue on __InputValue {\n      name\n      description\n      type { ...TypeRef }\n      defaultValue\n    }\n\n    fragment TypeRef on __Type {\n      kind\n      name\n      ofType {\n        kind\n        name\n        ofType {\n          kind\n          name\n          ofType {\n            kind\n            name\n            ofType {\n              kind\n              name\n              ofType {\n                kind\n                name\n                ofType {\n                  kind\n                  name\n                  ofType {\n                    kind\n                    name\n                  }\n                }\n              }\n            }\n          }\n        }\n      }\n    }\n  "}'.replace('\n','\\n')

class QueryRunner:
    
    @staticmethod
    def run_query(query): 
        url = QueryRunner.url
        cookies = None
        proxyDict = None
        headers = None
        if 'cookies' in dir(QueryRunner):
            cookies = QueryRunner.cookies
        if 'headers' in dir(QueryRunner):
            headers = QueryRunner.headers
        if 'proxy' in dir(QueryRunner):
            proxy = QueryRunner.proxy
            proxyDict = { 
             "https"   : proxy,
             "http"   : proxy
            }
        
        request = requests.post(url, json=query, proxies=proxyDict,verify=False,cookies=cookies,headers=headers)
        if request.status_code == 200:
            return request.json()
        else:
            return None

# Вершины графа будут такие:
# - идентификатор
# - имя типа
# 
# Ребра графа будут такие:
# - идентификатор вершины
# - ребенок
# - модификаторы ребер (имя для запроса, NON_NULL, LIST)
# 
# При обходе будет такая структура:
# - идентификатор 1 вершины
# - идентификатор 2 вершины
# - идентификатор 3 вершины
# ...
# - модификаторы 1-2
# - модификаторы 2-3 и т.д.

# ## Loops

def check_loop_for_list(loop):
    loop_begin = loop.ids.index(loop.id_to)
    for i in range(loop_begin,len(loop.ids)-1):
        if loop['LIST_%d_%d'%(i,i+1)] == True:
            return True
    return False

def get_full_type(t,modifiers=None):
    if modifiers is None:
        modifiers = []    
    if t['kind'] in ['NON_NULL','LIST']:
        return get_full_type(t['ofType'],modifiers+[t['kind']])
    return t['name'],modifiers

def build_graph(schema):
    types = schema['data']['__schema']['types']
    vertexes = []

    for i,t in enumerate(types):
        name = t['name']
        vertexes.append([i,name])

    vertexes = pd.DataFrame.from_records(vertexes,columns = ['id','name'])
    edges = []
    for i,t in enumerate(types):
        if ('fields' in t) and (t['fields']!=None):        
            for f in t['fields']:
                child_name, modifiers = get_full_type(f['type'])
                edges.append([i,vertexes[vertexes.name==child_name].id.values[0],f['name'],'NON_NULL' in modifiers, 'LIST' in modifiers])
    edges = pd.DataFrame.from_records(edges,columns = ['id_from','id_to','arg_name','NON_NULL','LIST'])
    return vertexes,edges

def find_loops(graph,query_type,mutation_type,loops_to_find=100):
    vertexes,edges = graph
    start = vertexes[vertexes.name.apply(lambda x: x in  [query_type,mutation_type])][['id']]
    start.columns=['id_0']
    start['ids'] = start.id_0.apply(lambda x: [x])
    start['start_word'] = [query_type,mutation_type]
    move = 0
    current = start
    loops = []
    while True:
        print ('%d iteration'% (move+1))
        result = current.merge(edges,left_on='id_%d'%move,right_on='id_from')
        if result.shape[0] == 0:
            break
        result.drop('id_from',axis=1,inplace=True)
        loops_recs = result.apply(lambda x: x.id_to in x.ids,axis=1)
        if loops_recs.any():
            print ('loops found')
            for name,row in result[loops_recs].iterrows():
                if check_loop_for_list(row):
                    loops.append(row)
                    if len(loops)>= loops_to_find:
                        return loops
            result.drop(result[loops_recs].index,inplace=True)
        result['ids'] = result.ids.apply(lambda x: x.copy())
        result.apply(lambda x: x.ids.append(x.id_to),axis=1)
        result.rename(columns = {'id_to':'id_%d'%(move+1),
                                 'NON_NULL':'NON_NULL_%d_%d'%(move,move+1),
                                 'arg_name':'arg_name_%d_%d'%(move,move+1),
                                 'LIST':'LIST_%d_%d'%(move,move+1)},inplace=True)

        current = result
        print (current.shape)
        move +=1 


def run_loops(loops,loop_depth = 3,not_more_than=16):
    for loop in loops:        
        loop_begin = loop.ids.index(loop.id_to)
        start_args = ['arg_name_%d_%d'%(i,i+1) for i in range(loop_begin)]
        prolog_strs = list(loop[start_args].values)
        loop_args = ['arg_name_%d_%d'%(i,i+1) for i in range(loop_begin,len(loop.ids)-1)]
        loop_strs = list(loop[loop_args].values) + [loop.arg_name]
        path = '|'.join([loop.start_word] + prolog_strs + loop_strs*loop_depth)
        print(path)
        run_queries_by_path(schema,path,not_more_than=not_more_than)

def find_alt_paths(graph,target,query_type,mutation_type):
    vertexes,edges = graph
    start = vertexes[vertexes.name == target][['id']]
    finish = vertexes[vertexes.name.apply(lambda x: x in  [query_type,mutation_type])].id.values
    start.columns=['id_0']
    start['ids'] = start.id_0.apply(lambda x: [x])
    move = 0
    current = start
    found_pathes = []
    while True:
        print ('%d iteration'% (move+1))
        result = current.merge(edges,left_on='id_%d'%move,right_on='id_to')
        if result.shape[0] == 0:
            break
        result.drop('id_to',axis=1,inplace=True)
        loops_recs = result.apply(lambda x: x.id_from in x.ids,axis=1)
        if loops_recs.any():
            result.drop(result[loops_recs].index,inplace=True)


        found = result.id_from.apply(lambda x: x in finish)
        if found.any():
            found_pathes.append(result[found])
            result.drop(result[found].index,inplace=True)

        result['ids'] = result.ids.apply(lambda x: x.copy())
        result.apply(lambda x: x.ids.append(x.id_from),axis=1)
        result.rename(columns = {'id_from':'id_%d'%(move+1),
                                 'NON_NULL':'NON_NULL_%d_%d'%(move,move+1),
                                 'arg_name':'arg_name_%d_%d'%(move,move+1),
                                 'LIST':'LIST_%d_%d'%(move,move+1)},inplace=True)

        current = result
        print (current.shape)
        move +=1 

    real_pathes = []
    for l in found_pathes:
        for name,row in l.iterrows():
            ids=[]
            for i in range(len(row.ids)-1):
                ids.append( 'arg_name_%d_%d'%(i,i+1))
            path = list(row[ids].values) + [row.arg_name]
            path += [vertexes[vertexes.id == row.id_from].name.values[0]]
            real_pathes.append('|'.join(path[::-1]))
    return real_pathes


def find_shortest_paths(graph,target,query_type,mutation_type):
    if target in [query_type,mutation_type]:
        return [target]
    vertexes,edges = graph
    start = vertexes[vertexes.name == target][['id']]
    finish = vertexes[vertexes.name.apply(lambda x: x in  [query_type,mutation_type])].id.values
    start.columns=['id_0']
    start['ids'] = start.id_0.apply(lambda x: [x])
    move = 0
    current = start
    found_pathes = []
    while True:
        result = current.merge(edges,left_on='id_%d'%move,right_on='id_to')
        if result.shape[0] == 0:
            break
        result.drop('id_to',axis=1,inplace=True)
        loops_recs = result.apply(lambda x: x.id_from in x.ids,axis=1)
        if loops_recs.any():
            result.drop(result[loops_recs].index,inplace=True)


        found = result.id_from.apply(lambda x: x in finish)
        if found.any():
            found_pathes.append(result[found])
            break

        result['ids'] = result.ids.apply(lambda x: x.copy())
        result.apply(lambda x: x.ids.append(x.id_from),axis=1)
        result.rename(columns = {'id_from':'id_%d'%(move+1),
                                 'NON_NULL':'NON_NULL_%d_%d'%(move,move+1),
                                 'arg_name':'arg_name_%d_%d'%(move,move+1),
                                 'LIST':'LIST_%d_%d'%(move,move+1)},inplace=True)

        current = result
        move +=1 

    real_pathes = []
    for l in found_pathes:
        for name,row in l.iterrows():
            ids=[]
            for i in range(len(row.ids)-1):
                ids.append( 'arg_name_%d_%d'%(i,i+1))
            path = list(row[ids].values) + [row.arg_name]
            path += [vertexes[vertexes.id == row.id_from].name.values[0]]
            real_pathes.append('|'.join(path[::-1]))
    return( real_pathes)


def find_all_paths_with_args(schema):
    graph = build_graph(schema)
    query_type = schema['data']['__schema']['queryType']['name']
    mutation_type = schema['data']['__schema']['mutationType']['name']
    result = []
    for t in types:
        if ('fields' not in t) or (t['fields'] is None):
            continue
        args = []
        for f in t['fields']:
            if len(f['args']) > 0:
                args.append(f['name'])
        if len(args) > 0:
            path_to_type = find_shortest_paths(graph,t['name'],query_type,mutation_type)
            if len(path_to_type)==0: #type unaccessible, bug in schema?
                continue
            path_to_type = path_to_type[0]
            for arg in args:
                result.append (path_to_type+'|'+arg)
    return result

def build_arg_definition_strings(args):
    if len(args)==0:
        return ''
    real_names = pyjq.all('.[].real_name',args)
    real_types = [build_type_string(x['type']) for x in args]
    arg_def_str = ', '.join(['$%s: %s' %(real_name,real_type) for real_name,real_type in zip(real_names,real_types)])
    return '(%s)'%arg_def_str
    
def build_arg_call_strings(args):
    if len(args)==0:
        return ''
    names = pyjq.all('.[].name',args)
    real_names = pyjq.all('.[].real_name',args)
    real_types = [build_type_string(x['type']) for x in args]
    call_args_str = ', '.join(['%s: $%s' %(name,real_name) for (name,real_name) in zip(names,real_names)])
    return '(%s)' % call_args_str

def build_arg_var(schema,arg_type,skip_nullable_vars):
    real_type = arg_type
    not_null = False
    if real_type['kind'] == 'NON_NULL':
        real_type = real_type['ofType']
        not_null = True
    if not not_null and skip_nullable_vars:
        return None
    if real_type['kind'] == 'LIST':
        if skip_nullable_vars:
            return []
        return [build_arg_var(schema,real_type['ofType'],skip_nullable_vars)]
    if real_type['kind'] == 'SCALAR':
        if real_type['name'] not in default_table:
            print ('%s not in default_table' % real_type['name'])
            return placehoder_table['String']
        return placehoder_table[real_type['name']]
    if real_type['kind'] == 'INPUT_OBJECT':
        obj_type = get_type_by_name(schema,real_type['name'])
        res = {}
        for f in obj_type['inputFields']:
            res[f['name']] = build_arg_var(schema,f['type'],skip_nullable_vars)
        return res



#Note: Date and DateTime are not graphQL scpecified. It is typical scalars, but format could be different
default_table = {'String':['"test_string"'],
                 'ID':['1','"5ed496cc-c971-11dc-93cd-15767af24309"'],
                 'Int':['1'],
                 'DateTime':['"2017-07-09T11:54:42"'],
                 'Date':['"2017-07-09"'],
                 'Float':['3.1415'],
                 'Boolean':['true'],
                 'URI':['"http://example.com/"']}

placehoder_table = {'String':'|String|',
                 'ID':'|ID|',
                 'Int':'|Int|',
                 'DateTime':'|DateTime|',
                 'Date':'|Date|',
                 'Float':'|Float|',
                 'Boolean':'|Boolean|',
                 'URI':'|URI|'}

def build_variables(schema,args,skip_nullable_vars):
    variables = {}
    for arg in args:
        variables[arg['real_name']] = build_arg_var(schema,arg['type'],skip_nullable_vars)

    variables_str = json.dumps(variables)

    variables_types = re.findall('\"\|([a-zA-Z]*)\|\"',variables_str)
    variables_values = [default_table[var_type] for var_type in variables_types]
    variables_values_all = itertools.product(*variables_values)

    results = []
    requests = 0
    for variables_values in variables_values_all:
        variables_str_for_test = variables_str
        for var_type,var_val in zip(variables_types,variables_values):
            variables_str_for_test = re.subn('\"\|([a-zA-Z]*)\|\"',var_val,variables_str_for_test,count=1)[0]
        results.append(json.loads(variables_str_for_test))
        requests += 1
        #if requests >= max_requests_per_operation:
        #    break
    return results

def find_scalar_fields(json_type):
    get_fields = []
    for f in json_type['fields']:
        field_type,field_name = get_return_type_name(f['type'])
        if field_type == 'SCALAR':
            get_fields.append(f['name'])
    return get_fields


def get_first_static_field(schema,typename):
    t = get_type_by_name(schema,typename)
    if ('fields' not in t) or (t['fields'] is None):
        return None
    for f in t['fields']:
        r_type = get_return_type_name(f['type'])
        if r_type[0] == 'SCALAR':
            return f['name']
    
    pathes = []
    for f in t['fields']:
        r_type = get_return_type_name(f['type'])
        subpath = get_first_static_field(schema,r_type[1])
        if subpath is None:
            continue
        pathes.append((f['name'],subpath,subpath.count('|')))
    
    pathes.sort(key=lambda x: x[1])
    return pathes[0][0] + '|' + pathes[0][1]

def build_query_by_path(schema,path):
    pattern = '''%s %s%s{%s}'''

    query_type = schema['data']['__schema']['queryType']['name']
    mutation_type = schema['data']['__schema']['mutationType']['name']

    in_path = path
    path = path.split('|')
    first_word = 'query' if path[0]==query_type else 'mutation'
    query_type = get_type_by_name(schema,path[0])
    query_name = '_'.join(path)
    current_type = query_type
    all_args = []
    indent = 0
    header = ''
    footer = ''
    for i,param in enumerate(path[1:]):
        target_field = copy(pyjq.all('.[] | select(.name == "%s")'%param,current_type['fields'])[0])
        for arg in target_field['args']:
            arg['real_name'] = arg['name'] + '_%d' % i
        param_type,param_kind = get_valuable_type(target_field['type'])

        call_args = build_arg_call_strings(target_field['args'])
        all_args += target_field['args']

        indent += 4
        header += '\n' + ' ' * indent
        header += param+call_args
        header += '{'
        footer = ' ' * indent + '}\n' + footer

        current_type = get_type_by_name(schema,param_type)
    header = header[:-1]
    footer = '\n'.join(footer.split('\n')[1:])



    return_type_type,return_type_name = get_return_type_name(target_field['type'])
    if return_type_type in ['SCALAR','ENUM']:
        return_data = ''
    else:
        return_type = get_type_by_name(schema,return_type_name)
        json_type = return_type
        
        field_names = pyjq.all('.fields[].name',json_type)

        get_fields = find_scalar_fields(json_type)
        
    #     if 'edges' in field_names:
    #         print( build_query_by_path(schema,in_path+'|edges|node'))
    #         edges = pyjq.all('.[] | select(.name == "edges")',json_type['fields'])[0]
    #         edges_type = get_valuable_type(edges['type'])[0]
    #         edges_type = get_type_by_name(schema,edges_type)
    #         nodes = pyjq.all('.[] | select(.name == "node")',edges_type['fields'])[0]
    #         nodes = pyjq.all('.[] | select(.name == "node")',edges_type['fields'])[0]
    #         real_type = get_valuable_type(nodes['type'])[0]
    #         real_type = get_type_by_name(schema,real_type)
    #         params = find_scalar_fields(real_type)
    #         edges_pattern_head = '''edges{
    #     node{\n'''
    #         edges_pattern_footer='''    }
    # }'''
    #         nodes_fields = '\n'.join([' '*4*2 + param for param in params]) + '\n'
    #         edges_str = edges_pattern_head + nodes_fields + edges_pattern_footer
    #         get_fields += edges_str.split('\n')
        
        if len(get_fields) == 0:
                ## find inner path
            new_path = get_first_static_field(schema,return_type_name)
            full_new_path = in_path+ '|' + new_path
            return (build_query_by_path(schema,full_new_path))

        fields = ''
        for f in get_fields:
            fields+= ' '*4*(len(path)+1) + f + '\n'
        fields+= ' '*4*(len(path))
        return_data = '{\n%s}\n'%fields

    head_args = build_arg_definition_strings(all_args)
    query_str = (pattern%(first_word,query_name,head_args,header+return_data+footer))
    query_vars = build_variables(schema,all_args,True)
    return query_str,query_vars,query_name


def run_queries_by_path(schema,path,not_more_than=None):
    print (path)
    query_str,query_vars,query_name = build_query_by_path(schema,path)

    requests_set = [{'operation':query_name,
                   'variables':v,
                   'query':query_str} for v in query_vars]
    for r in requests_set[:not_more_than]:
        QueryRunner.run_query(r)    


def get_type_by_name(schema,type_name):
    types = schema['data']['__schema']['types']
    for t in types:
        if t['name'] == type_name:
            return t

def get_operations_in_type(schema,json_type):
    results = []
    if ('fields' not in json_type) or (json_type['fields'] == None):
        return []
    for f in json_type['fields']:
        is_func = None
        if len(f['args'])>0:
            is_func = True
        elif f['type']['name'] is None:
            is_func = True
        elif f['type']['ofType'] is None:
            is_func = False
        else:
            sub_type = get_type_by_name(schema,f['type']['name'])
            field_names = pyjq.all('.fields[].name',sub_type)
            if 'id' in field_names:
                is_func=True
            else:
                is_func = False
        if is_func == False:
            sub_type = get_type_by_name(schema,f['type']['name'])
            if sub_type is None:
                continue

            res = get_operations_in_type(schema,sub_type)
            for r in res:
                r['full_name'] = f['name']+'|'+r['full_name']
                results.append(r)
        else: 
            f['full_name'] = f['name']
            results.append(f)
    return results

def build_type_string(t):
    if t['kind'] == 'NON_NULL':
        return build_type_string(t['ofType']) + '!'
    if t['kind'] == 'LIST':
        return '[' + build_type_string(t['ofType']) + ']'
    return t['name']

def build_arg_strings(args):
    if len(args)==0:
        return None,None
    names = pyjq.all('.[].name',args)
    real_types = [build_type_string(x['type']) for x in args]
    first_args = ', '.join(['$%s: %s' %(name,real_type) for name,real_type in zip(names,real_types)])
    second_args = ', '.join(['%s: $%s' %(name,name) for name in names])
    return first_args,second_args

def get_return_type_name(query):
    if query['name'] is not None:
        return query['kind'],query['name']
    else:
        return get_return_type_name(query['ofType'])

def get_valuable_type(Type):
    if Type['kind']=='NON_NULL':
        return get_valuable_type(Type['ofType'])
    if Type['kind']=='LIST':
        return get_valuable_type(Type['ofType'])
    return Type['name'],Type['kind']

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-u","--url",
                        help="GraphQL endpoint url")
    parser.add_argument("-f","--file",
                        help = "file with introspection query response");
    parser.add_argument("-m","--mode",
                        help="mode from [elementary,all_args,loops,alt_path,single_query]")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="increase output verbosity",)
    parser.add_argument("-c","--cookie",action="append",
                        help="auth cookie")
    parser.add_argument("--loop-depth",help = "define depth for loops (loops mode only)",default=3)
    parser.add_argument("--loop-number",help = "number of loops requests to issue (loops mode only)",default=100)
    parser.add_argument("--skip-nullable",help = "set none to nullable variables")
    parser.add_argument("--target-class",help = "target class name (for alt_path mode only)")
    parser.add_argument("-p","--proxy",help = "proxy in python requests format")
    parser.add_argument("--max-requests-per-call", help = "limit number of issued requests with different parameter formats",default=16)
    parser.add_argument('--header', help = "HTTP header",action="append")
    parser.add_argument('--mutation', action="store_true",help = "set to use mutation queries (May be dangerous)")
    parser.add_argument('--path', help = "path to run single call, example: Query|getUsers|posts (single_query mode only)")
    args = parser.parse_args()
    schema = None

    if args.url is None:
        print ("provide graphql endpoint url (-u)")
        exit(1)

    QueryRunner.url = args.url

    if args.file is not None:
        schema = open(args.file).read()
        
    if args.cookie is not None:
        cookie_dir = {}
        for cookie in args.cookie:
            splits = cookie.split('=',1)
            if len(splits)==1:
                cookie_dir[splits[0]]=''
            else:
                cookie_dir[splits[0]]=splits[1]
        QueryRunner.cookies = cookie_dir

    if args.header is not None:
        header_dir = {}
        for header in args.header:
            splits = header.split('=',1)
            if len(splits)==1:
                header_dir[splits[0]]=''
            else:
                header_dir[splits[0]]=splits[1]
        QueryRunner.headers = header_dir

    if args.proxy is not None:
        QueryRunner.proxy = args.proxy

    if (args.mode is None) or (args.mode not in 'elementary,all_args,loops,alt_path,single_query'.split(',')):
        print ("provide -m with one of [elementary,all_args,loops,alt_path,single_query] value")
        exit(1)
    mode = args.mode
    mutation = args.mutation == True
        
    if schema is None:
        schema = QueryRunner.run_query(json.loads(introspection_query))

    query_type_name = schema['data']['__schema']['queryType']['name']
    mutation_type_name = schema['data']['__schema']['mutationType']['name']
    

    if mode == 'elementary':
        query_type = get_type_by_name(schema,query_type_name)
        mutation_type = get_type_by_name(schema,mutation_type_name)
        queries = get_operations_in_type(schema,query_type)
        for q in queries:
            path = query_type_name + '|'+q['full_name']
            run_queries_by_path(schema,path,not_more_than=args.max_requests_per_call)
        if mutation:
            mutations = get_operations_in_type(schema,mutation_type)
            for m in mutations:
                path = mutation_type_name + '|'+q['full_name']
                run_queries_by_path(schema,path,not_more_than=args.max_requests_per_call)
        print ('Done')
        exit(0)

    if mode == 'all_args':
        paths = find_all_paths_with_args(schema)
        if not mutation:
            paths = list(filter(lambda x: x[:len(mutation_type_name)]!=mutation_type_name,paths))
        for path in paths:
            run_queries_by_path(schema,path,not_more_than=args.max_requests_per_call)
        
    if mode == 'loops':
        graph = build_graph(schema)
        loops = find_loops(graph,query_type_name,mutation_type_name,loops_to_find = args.loop_number)

        run_loops(loops,loop_depth = args.loop_depth,not_more_than=args.max_requests_per_call)
        print ('Done')
        exit(0)

    if mode == 'single_query':
        run_queries_by_path(schema,args.path,not_more_than = args.max_requests_per_call)
        print ('Done')
        exit(0)

    if mode == 'alt_path':
        if args.target_class is None:
            print ("Provide --target-class for alt_paths mode")
            exit(1)
        graph = build_graph(schema)
        print (find_alt_paths(graph,args.target_class,query_type_name,mutation_type_name))
        print ('Done')
        exit(0)


if __name__=='__main__':
    main()





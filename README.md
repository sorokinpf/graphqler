# graphrler

Helps in security testing graphql applications

## Setup

```
pip install -r requirements.txt
```

## Modes

- elementary: issue all elementary queries
- all_args: find all types with fields with parameters and issue query for each
- loops: find defined number of loops and issue query for each
- alt_path: find all pathes to given type
- single_query: issue single query


```
usage: graphqler.py [-h] [-u URL] [-f FILE] [-m MODE] [-v] [-c COOKIE]
                    [--loop-depth LOOP_DEPTH] [--loop-number LOOP_NUMBER]
                    [--skip-nullable SKIP_NULLABLE]
                    [--target-class TARGET_CLASS] [-p PROXY]
                    [--max-requests-per-call MAX_REQUESTS_PER_CALL]
                    [--header HEADER] [--mutation] [--path PATH]

optional arguments:
  -h, --help            show this help message and exit
  -u URL, --url URL     GraphQL endpoint url
  -f FILE, --file FILE  file with introspection query response
  -m MODE, --mode MODE  mode from
                        [elementary,all_args,loops,alt_path,single_query]
  -v, --verbose         increase output verbosity
  -c COOKIE, --cookie COOKIE
                        auth cookie
  --loop-depth LOOP_DEPTH
                        define depth for loops (loops mode only)
  --loop-number LOOP_NUMBER
                        number of loops requests to issue (loops mode only)
  --skip-nullable SKIP_NULLABLE
                        set none to nullable variables
  --target-class TARGET_CLASS
                        target class name (for alt_path mode only)
  -p PROXY, --proxy PROXY
                        proxy in python requests format
  --max-requests-per-call MAX_REQUESTS_PER_CALL
                        limit number of issued requests with different
                        parameter formats
  --header HEADER       HTTP header
  --mutation            set to use mutation queries (May be dangerous)
  --path PATH           path to run single call, example: Query|getUsers|posts
                        (single_query mode only)```

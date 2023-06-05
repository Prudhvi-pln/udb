__author__ = 'Prudhvi PLN'

from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
from time import sleep


# custom decorator for retring of a function
def retry(exceptions=(Exception,), tries=3, delay=2, backoff=2):
    """
    Retry Decorator
    Retries the wrapped function/method `times` times if the exceptions listed
    in ``exceptions`` are thrown
    :param Exceptions: Lists of exceptions that trigger a retry attempt
    :type Exceptions: Tuple of Exceptions
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt, mdelay = 0, delay
            while attempt < tries:
                try:
                    return_status = func(*args, **kwargs)
                    if 'ERROR' in return_status:
                        raise Exception(return_status)
                    return return_status
                except exceptions as e:
                    # print(f'{e} | Attempt: {attempt} / {tries}')
                    sleep(mdelay)
                    attempt += 1
                    mdelay *= backoff
                    if attempt >= tries:
                        print(f'{e} | Final Attempt: {attempt} / {tries}')
            return func(*args, **kwargs)
        return wrapper
    return decorator

# custom decorator to make any function multi-threaded
def threaded(max_parallel=None, thread_name_prefix='udb-', print_status=False):
    '''
    make any function multi-threaded by adding this decorator
    '''
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            final_status = []
            results = {}
            # Using a with statement to ensure threads are cleaned up promptly
            with ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix=thread_name_prefix) as executor:

                futures = { executor.submit(func, i, *args[1:], **kwargs): idx for idx, i in enumerate(args[0]) }

                for future in as_completed(futures):
                    i = futures[future]
                    try:
                        # store result
                        data = future.result()
                        # if 'completed' not in data:
                        #     print(data)
                        if print_status: print(f"\033[F\033[K\r{data}")
                        results[i] = data
                    except Exception as e:
                        print(f'{e}')

            # sort the results in same order as received
            for idx, status in sorted(results.items()):
                final_status.append(status)

            return final_status
        return wrapper
    return decorator

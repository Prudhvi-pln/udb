__author__ = 'Prudhvi PLN'

import logging
import os
import re
import requests
import sys
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
from time import sleep
from logging.handlers import RotatingFileHandler
from subprocess import Popen, PIPE


# color themes
PRINT_THEMES = {
    'default': '\033[1m',       # white
    'blurred': '\033[90m',      # black
    'header': '\033[92m',       # green
    'results': '\033[94m',      # blue
    'predefined': '\033[33m',   # dark yellow
    'user_input': '\033[93m',   # yellow
    'yellow': '\033[93m',       # yellow
    'success': '\033[32m',      # dark green
    'error': '\033[91m',        # red
    'blinking': '\033[5m',
    'reset': '\033[0m'
}
DISPLAY_COLORS = True

# strip ANSI characters, to write to log file
strip_ansi = lambda text: re.sub(r'\x1b\[[0-9;]*m', '', text)

class ExitException(Exception):
    '''
    Custom exception which forces UDB to exit
    '''
    pass

def get_current_version():
    '''
    Returns the current version of UDB
    '''
    with open(os.path.join(os.path.dirname(__file__), 'version.txt'), 'r') as f:
        current_version = f.read().strip()

    return current_version

def check_for_updates(current_version):
    '''
    Check for the latest UDB version. Uses `version.txt` from GitHub Repo.
    Returns:
    - status code: 0=INFO, 1=WARN, 2=ERROR
    - status message
    '''
    # get latest version from GitHub
    try:
        latest_version = requests.get('https://github.com/Prudhvi-pln/udb/blob/main/Utils/version.txt', headers={'accept': 'application/json'}).json()['payload']['blob']['rawLines'][0]
    except Exception as e:
        return (2, f'ERROR: Unable to retrieve latest version information from Git')

    # compare the versions
    if current_version != latest_version:
        return (1, f'WARNING: Latest version {latest_version} available. Consider upgrading to the latest version by running: python udb.py --update')
    else:
        return (0, f'Current version {current_version} is already the latest')

def exec_os_cmd(cmd):
    '''
    Execute any OS commands
    Args: command to be executed
    Returns: output of executed command
    '''
    proc = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=True)
    # print stdout to console
    msg = proc.communicate()[0].decode("utf-8")
    std_err = proc.communicate()[1].decode("utf-8")
    rc = proc.returncode
    if rc != 0:
        raise Exception(f"Error occured: {std_err}")
    return msg

def update_udb():
    '''
    Update UDB to the latest version available from Git
    '''
    colprint('predefined', 'Updating UDB to the latest version...')
    try:
        print(exec_os_cmd('git pull'))
    except Exception as e:
        colprint('error', f'Failed to update UDB:\n{e}')

# display seconds in hh mm ss format
def pretty_time(sec: int, fmt='hh:mm:ss'):
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 3600 % 60
    if fmt == 'hh:mm:ss':
        return '{:02d}:{:02d}:{:02d}'.format(h,m,s)
    else:
        return '{:02d}h {:02d}m {:02d}s'.format(h,m,s) if h > 0 else '{:02d}m {:02d}s'.format(m,s)

# initialize colored printing
def colprint_init(disable_colors):
    if disable_colors:
        global DISPLAY_COLORS
        DISPLAY_COLORS = False
    else:
        os.system('')   # required to enable ANSI output in Windows terminals

# custom stdout printer
def colprint(theme, text, **kwargs):
    '''Colorful print function.

    Args:
    - theme: color theme to be applied
    - text: data to print
    '''
    if DISPLAY_COLORS:
        c_strt, c_end = PRINT_THEMES.get(theme, '\033[1m'), PRINT_THEMES["reset"]
    else:
        c_strt, c_end = '', ''

    # parse the additional arguments
    line_end = kwargs.get('end')
    input_type = kwargs.get('input_type')
    input_dtype = kwargs.get('input_dtype')
    input_options = kwargs.get('input_options')
    allow_empty_input = kwargs.get('allow_empty_input', True)

    def _get_input_(msg, input_type='once', input_dtype=None, input_options=[], allow_empty_input=True):
        user_input = input(f'{msg}').strip()
        # do not return till valid input is entered
        if input_type == 'recurring':
            try:
                # data type check
                try:
                    if user_input == '' and allow_empty_input:
                        return user_input       # if it is empty, it means default value
                    elif input_dtype == 'int':
                        user_input = int(user_input)
                    elif input_dtype == 'float':
                        user_input = float(user_input)
                    elif input_dtype == 'range':
                        # special case for range inputs. check if the values in range are int / float. allow empty value.
                        temp_inputs = [ float(i) if '.' in i else int(i) for i in user_input.replace('-', ',').split(',') if i ]
                except ValueError:
                    raise ValueError('Invalid input! Please enter a valid input.')

                # valid input check
                if input_options and not user_input in input_options:
                    raise ValueError('Invalid option selected! Please select an option from above.')

            except ValueError as ve:
                logging.error(ve)
                return _get_input_(msg, input_type, input_dtype, input_options, allow_empty_input)

        return user_input

    if 'input' in theme:
        return _get_input_(f'{c_strt}{text}{c_end}', input_type, input_dtype, input_options, allow_empty_input)
    else:
        print(f'{c_strt}{text}{c_end}', end=line_end)

# custom decorator for retring of a function
def retry(exceptions=(Exception,), tries=3, delay=2, backoff=2, print_errors=False):
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
                    if type(return_status) == tuple and return_status[1] == 0:
                        raise Exception(return_status)
                    return return_status
                except exceptions as e:
                    # colprint('error', f'{e} | Attempt: {attempt} / {tries}')
                    sleep(mdelay)
                    attempt += 1
                    mdelay *= backoff
                    if attempt >= tries and print_errors:
                        colprint('error', f'{e} | Final Attempt: {attempt} / {tries}')
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
            # If first argument is 'self' keyword, value will be like <xxx object at xxx>, then it is called from a class
            called_from_class = True if str(args[0]).startswith('<') and str(args[0]).endswith('>') and 'object at' in str(args[0]) else False
            final_status = []
            results = {}
            # Using a with statement to ensure threads are cleaned up promptly
            with ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix=thread_name_prefix) as executor:

                if called_from_class:
                    # If caller is a class, need to provide first argument (i.e., self) separately
                    futures = { executor.submit(func, args[0], i, *args[2:], **kwargs): idx for idx, i in enumerate(args[1]) }
                else:
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
                        colprint('error', f'{e}')

            # sort the results in same order as received
            for idx, status in sorted(results.items()):
                final_status.append(status)

            return final_status
        return wrapper
    return decorator

# load yaml config into dict
def load_yaml(config_file):
    if not os.path.isfile(config_file):
        colprint('error', f'Config file [{config_file}] not found')
        raise ExitException(0)

    with open(config_file, "r") as stream:
        try:
            return yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            colprint('error', f"Error occured while reading yaml file: {exc}")
            raise ExitException(0)

# custom logging formatter to highlight error messages
class CustomLogFormatter(logging.Formatter):
    '''A Formatter to highlight error log level messages in red'''
    def __init__(self, fmt=None, datefmt=None, style='%', validate=True):
        super().__init__(fmt, datefmt, style, validate)

    def format(self, record):
        if record.levelname == 'ERROR' and DISPLAY_COLORS:
            record.msg = f'{PRINT_THEMES["error"]}{record.msg}{PRINT_THEMES["reset"]}'
        return super().format(record)

# custom logger function
def create_logger(**logger_config):
    '''Create a logging handler

    Args: logging configuration as a dictionary [Allowed keys: log_level, log_dir, log_filename, max_log_size_in_kb, log_backup_count]
    Returns: a logging handler'''
    # human-readable log-level to logging.* mapping
    log_levels = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR
    }

    # set default logging configuration
    default_logging_config = {
        'log_level': 'INFO',
        'log_dir': 'log',
        'log_filename': 'udb.log',
        'max_log_size_in_kb': 1000,
        'log_backup_count': 3
    }

    # update missing logging configuration with defaults
    for key in default_logging_config.keys():
        if key not in logger_config:
            logger_config[key] = default_logging_config[key]

    # format the log entries
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)s - %(message)s')
    stdout_formatter = CustomLogFormatter()
    # get root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # create logging directory
    if logger_config['log_dir']: os.makedirs(logger_config['log_dir'], exist_ok=True)

    # create logging handler for stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(stdout_formatter)
    stdout_handler.setLevel(logging.ERROR)

    # add rotating file handler to rotate log file when size crosses a threshold
    file_handler = RotatingFileHandler(
        os.path.join(logger_config['log_dir'], logger_config['log_filename']),
        maxBytes = logger_config['max_log_size_in_kb'] * 1000,  # KB to Bytes
        backupCount = logger_config['log_backup_count'],
        encoding='utf-8'
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(log_levels.get(logger_config['log_level'].upper()))

    logger.addHandler(file_handler)     # print to file
    logger.addHandler(stdout_handler)   # print only error to stdout

    return logger

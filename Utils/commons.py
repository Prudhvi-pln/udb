__author__ = 'Prudhvi PLN'

import logging
import os
import re
import requests
import sys
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
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
# parse semantic version string
parse_version = lambda version: tuple(map(int, (version.split('.') + ['0', '0'])[:3]))

class ExitException(Exception):
    '''
    Custom exception which forces UDB to exit. Requires status code as argument.
    - =0 means direct exit without prompting for new session.
    - >0 prompts for new session.
    '''
    pass

class VersionManager():
    '''
    VersionManager to handle version checks and updates to UDB
    '''
    def __init__(self):
        self.parse_version = lambda version: tuple(map(int, (version.split('.') + ['0', '0'])[:3]))
        self.current_version = self.get_current_version()
        self.latest_changelog = self.get_latest_changelog()
        if self.latest_changelog:
            self.latest_version = next(iter(self.latest_changelog.keys()))
            self.update_status = self.check_for_updates()

    def _convert_md_to_json(self, data):
        cl = {}
        version = None
        for i in data:
            if i.startswith('## Version'):
                version = i.split()[2]
                cl[version] = []
            elif i.strip().startswith('-'):
                cl[version].append(i.strip())
        return cl

    def get_current_version(self):
        '''
        Returns the current version of UDB. Fetches current version from the local CHANGELOG.md
        '''
        with open(os.path.join(os.path.dirname(__file__), '..', 'CHANGELOG.md'), 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith('## Version'):
                    current_version = line.strip().split()[2]
                    break       # read the first version and break, to avoid loading entire file

        return current_version

    def get_latest_changelog(self):
        '''
        Retrieve the latest CHANGELOG from the GitHub repo and returns as a json
        '''
        latest_changelog = {}
        try:
            response = requests.get('https://github.com/Prudhvi-pln/udb/blob/main/CHANGELOG.md?plain=1', headers={'Accept': 'application/json'}).json()['payload']['blob']['rawLines']
            latest_changelog = self._convert_md_to_json(response)
        except Exception as e:
            pass

        return latest_changelog

    def check_for_updates(self):
        '''
        Check for the latest UDB version. Uses `CHANGELOG.md` from GitHub Repo.
        Returns:
        - status code: 0=INFO, 1=WARN, 2=ERROR
        - status message
        '''
        if not self.latest_changelog:
            return (2, f'ERROR: Unable to retrieve latest version information from Git')

        # compare the versions
        if self.parse_version(self.latest_version) > self.parse_version(self.current_version):
            return (1, f'WARNING: Latest version {self.latest_version} available. Consider upgrading to the latest version by running: python udb.py --update')
        else:
            return (0, f'Current version {self.current_version} is already the latest')

    def display_changelog(self):
        '''
        Display the changelog for available latest versions
        '''
        if self.update_status[0] != 1: return
        colprint('header', '\nChangelog:')
        for version in self.latest_changelog:
            if self.parse_version(version) >= self.parse_version(self.current_version):
                colprint('success', version)
                print('\n'.join(self.latest_changelog[version]))

    def update_udb(self):
        '''
        Update UDB to the latest version available from Git
        '''
        if self.update_status[0] == 1:
            # Show changelog before updating
            self.display_changelog()
            # Get confirmation to update
            proceed = colprint('user_input', f'\nUpdate UDB to latest version [{self.latest_version}] (y|n)? ', input_type='recurring', input_options=['y', 'n', 'Y', 'N']).lower() or 'y'
            if proceed != 'y':
                raise ExitException(0)
            colprint('predefined', 'Updating UDB to the latest version...')
            try:
                print(exec_os_cmd('git pull'))
                colprint('header', f'UDB updated to version {self.latest_version}')
            except Exception as e:
                colprint('error', f'Failed to update UDB:\n{e}')
        elif self.update_status[0] == 0:
            colprint('header', self.update_status[1])

        raise ExitException(0)

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

    Args: logging configuration as a dictionary [Allowed keys: log_level, log_dir, log_file_name, max_log_size_in_kb, log_backup_count]
    Returns: a logging handler'''
    # human-readable log-level to logging.* mapping
    log_levels = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR
    }

    # format the log entries
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)s - %(message)s')
    stdout_formatter = CustomLogFormatter()
    # get root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # create logging directory
    os.makedirs(logger_config.get('log_dir', 'logs'), exist_ok=True)

    # create logging handler for stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(stdout_formatter)
    stdout_handler.setLevel(logging.ERROR)

    # add rotating file handler to rotate log file when size crosses a threshold
    file_handler = RotatingFileHandler(
        os.path.join(logger_config.get('log_dir', 'logs'), logger_config.get('log_file_name', 'udb.log')),
        maxBytes = logger_config.get('max_log_size_in_kb', 1000) * 1000,  # KB to Bytes
        backupCount = logger_config.get('log_backup_count', 3),
        encoding='utf-8',
        delay=True
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(log_levels.get(logger_config.get('log_level', 'INFO').upper()))

    logger.addHandler(file_handler)     # print to file
    logger.addHandler(stdout_handler)   # print only error to stdout

    return logger

# delete old log files
def delete_old_logs(directory='logs', days_threshold=7, max_file_count=3):
    '''
    Delete files older than `days_threshold` days and greater than `max_file_count` in the specified directory.
    '''
    logging.debug(f'Deleting log files older than {days_threshold} days and greater than {max_file_count}...')
    ndays = datetime.now().timestamp() - days_threshold * 86400

    # Get list of files to delete. If you encapsulate this in () brackets, it'll be a generator :)
    files_with_mtime = [ (f, os.stat(f).st_mtime) for f in ( os.path.join(directory, i) for i in os.listdir(directory) ) if os.path.isfile(f) and os.stat(f).st_mtime < ndays ]
    files_to_delete = sorted(files_with_mtime, key=lambda x: x[1])[:-max_file_count]

    logging.debug(f'Found {len(files_to_delete)} files to delete!')
    failure_cnt = 0
    for f in files_to_delete:
        try:
            logging.debug(f'Deleting file: {f[0]}')
            os.remove(f[0])
        except:
            failure_cnt += 1
    
    if failure_cnt > 0:
        logging.error(f'Failed to delete {failure_cnt}/{len(files_to_delete)} log files older than {days_threshold} days.')
    else:
        logging.debug(f'Deleted {len(files_to_delete)} files.')

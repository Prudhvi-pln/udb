__author__ = 'Prudhvi PLN'

import argparse
from datetime import datetime
import os
from time import time
import traceback

from Clients.AnimeClient import AnimeClient
from Clients.DramaClient import DramaClient
from Utils.BaseDownloader import BaseDownloader
from Utils.HLSDownloader import HLSDownloader
from Utils.commons import check_version, create_logger, threaded, load_yaml


def get_series_type(keys, predefined_input=None):
    logger.debug('Selecting the series type')
    types = {}
    print('\nSelect type of series:')
    for idx, typ in enumerate(keys):
        if typ not in ['DownloaderConfig', 'LoggerConfig']:
            print(f'{idx+1}: {typ.capitalize()}')
            types[idx+1] = typ

    if predefined_input:
        print(f'\nUsing Predefined Input: {predefined_input}')
        series_type = predefined_input
    else:
        series_type = int(input('\nEnter your choice: '))

    logger.debug(f'Series type selected: {series_type}')

    if series_type not in types:
        raise Exception('Invalid input!')
    else:
        return types[series_type]

def search_and_select_series(predefined_search_input=None, predefined_year_input=None):
    while True:
        logger.debug("Search and select series")
        # get search keyword from user input
        if predefined_search_input:
            print(f'\nUsing Predefined Input for search: {predefined_search_input}')
            keyword = predefined_search_input
        else:
            keyword = input("\nEnter series/movie name: ")

        # search with keyword and show results
        print("\nSearch Results:")
        logger.info(f'Searching with keyword: {keyword}')
        search_results = client.search(keyword)
        logger.debug(f'Search Results: {search_results}')

        if search_results is None or len(search_results) == 0:
            logger.error('No matches found. Try with different keyword')
            continue

        print("\nEnter 0 to search with different key word")

        # get user selection for the search results
        try:
            option = -1
            if predefined_year_input:
                # get key from search_results where year is predefined_year_input
                for idx, result in search_results.items():
                    if int(result['year']) == predefined_year_input:
                        option = idx
                        break
                print(f'\nSelected option based on predefined year [{predefined_year_input}]: {option}')
            elif option < 0:
                option = int(input("\nSelect one of the above: "))
        except ValueError as ve:
            logger.error("Invalid input!")
            exit(1)

        logger.debug(f'Selected option: {option}')

        if option < 0 and predefined_year_input:
            logger.error('No results found based on predefined input')
            exit(1)
        elif option < 0 or option > len(search_results):
            logger.error(f'Invalid option selected: {option}')
            exit(1)
        elif option == 0:
            continue
        else:
            break

    return search_results[option]

def get_resolutions(items):
    '''
    genarator function to yield the resolutions of available episodes
    '''
    for item in items:
        yield [ i for i in item.keys() if i not in ('error', 'original') ]

def downloader(ep_details, dl_config):
    '''
    download function where Download Client initialization and download happens.
    Accepts two dicts: download config, episode details. Returns download status.
    '''
    get_current_time = lambda fmt='%F %T': datetime.now().strftime(fmt)
    start = get_current_time()
    start_epoch = int(time())

    out_file = ep_details['episodeName']

    if 'downloadLink' not in ep_details:
        return f'[{start}] Download skipped for {out_file}, due to error: {ep_details.get("error", "Unknown")}'

    download_link = ep_details['downloadLink']
    download_type = ep_details['downloadType']
    referer = ep_details['refererLink']
    out_dir = dl_config['download_dir']

    # create download client for the episode based on type
    if download_type == 'hls':
        logger.debug(f'Creating HLS download client for {out_file}')
        dlClient = HLSDownloader(dl_config, referer, out_file)

    elif download_type == 'mp4':
        logger.debug(f'Creating MP4 download client for {out_file}')
        dlClient = BaseDownloader(dl_config, referer, out_file)

    else:
        return f'[{start}] Download skipped for {out_file}, due to unknown download type [{download_type}]'

    logger.info(f'Download started for {out_file}...')

    if os.path.isfile(os.path.join(f'{out_dir}', f'{out_file}')):
        # skip file if already exists
        return f'[{start}] Download skipped for {out_file}. File already exists!'
    else:
        try:
            # main function where HLS download happens
            status, msg = dlClient.start_download(download_link)
        except Exception as e:
            status, msg = 1, str(e)

        # remove target dirs if no files are downloaded
        dlClient._cleanup_out_dirs()

        end = get_current_time()
        if status != 0:
            return f'[{end}] Download failed for {out_file}, with error: {msg}'

        def pretty_time(sec):
            h, m, s = sec // 3600, sec % 3600 // 60, sec % 3600 % 60
            return '{:02d}h {:02d}m {:02d}s'.format(h,m,s) if h > 0 else '{:02d}m {:02d}s'.format(m,s)
        end_epoch = int(time())
        download_time = pretty_time(end_epoch-start_epoch)
        return f'[{end}] Download completed for {out_file} in {download_time}!'

def batch_downloader(download_fn, links, dl_config, max_parallel_downloads):

    @threaded(max_parallel=max_parallel_downloads, thread_name_prefix='udb-', print_status=False)
    def call_downloader(link, dl_config):
        return download_fn(link, dl_config)

    dl_status = call_downloader(links.values(), dl_config)
    # show download status at the end, so that progress bars are not disturbed
    print("\033[K") # Clear to the end of line
    width = os.get_terminal_size().columns
    print('\u2500' * width)
    status_str = 'Download Summary:'
    for status in dl_status:
        status_str += f'\n{status}'
    # Once chatGPT suggested me to reduce 'print' usage as it involves IO to stdout
    print(status_str); logger.info(status_str)
    print('\u2500' * width)


if __name__ == '__main__':
    try:
        # check for latest version
        __version__, status_code, status_message = check_version()
        if status_code != 0:
            print(status_message)

        # parse cli arguments
        parser = argparse.ArgumentParser(description='UDB Client to download entire anime / drama in one-shot.')
        parser.add_argument('-c', '--conf', default='config_udb.yaml',
                            help='configuration file for udb client (default: config_udb.yaml)')
        parser.add_argument('-v', '--version', action="version", version=f"{os.path.basename(__file__)} v{__version__}")
        parser.add_argument('-s', '--series-type', type=int, help='type of series')
        parser.add_argument('-n', '--series-name', help='name of the series to search')
        parser.add_argument('-y', '--series-year', type=int, help='release year of the series')
        parser.add_argument('-e', '--episodes', action='append', help='episodes number to download')
        parser.add_argument('-r', '--resolution', type=str, help='resolution to download the episodes')
        parser.add_argument('-d', '--start-download', action='store_true', help='start download immediately or not')


        args = parser.parse_args()
        config_file = args.conf
        series_type_predef = args.series_type
        series_name_predef = args.series_name
        series_year_predef = args.series_year
        episodes_predef = '-'.join(args.episodes) if args.episodes else None
        resolution_predef = args.resolution
        # convert bool to y/n
        start_download_predef = 'y' if args.start_download else None

        # load config from yaml to dict using yaml
        config = load_yaml(config_file)
        downloader_config = config['DownloaderConfig']
        max_parallel_downloads = downloader_config['max_parallel_downloads']

        # create logger
        logger = create_logger(**config['LoggerConfig'])
        logger.info(f'-------------------------------- NEW UDB INSTANCE v{__version__} --------------------------------')

        logger.info(f'CLI options: {config_file = }, {series_type_predef = }, {series_name_predef = }, {series_year_predef = }, {episodes_predef = }, {resolution_predef = }, {start_download_predef = }')

        # get series type
        series_type = get_series_type(config.keys(), series_type_predef)
        logger.info(f'Selected Series type: {series_type}')

        # create client
        if 'anime' in series_type.lower():
            logger.debug('Creating Anime client')
            client = AnimeClient(config[series_type])
        else:
            logger.debug('Creating Drama client')
            client = DramaClient(config[series_type])
        logger.info(f'Client: {client}')

        # set respective download dir if present
        if 'download_dir' in config[series_type]:
            logger.debug('Setting download dir from series specific configuration')
            downloader_config['download_dir'] = config[series_type]['download_dir']

        # modify path based on platform
        tmp_path = downloader_config['download_dir']
        if os.sep == '\\' and '/mnt/' in tmp_path:
            # platform is Windows and path is Linux, then convert to Windows path
            logger.debug('Platform is Windows but Paths are Linux. Converting paths to Windows paths')
            tmp_path = tmp_path.split('/')[2:]
            tmp_path[0] = tmp_path[0].upper() + ':'
            tmp_path = '\\'.join(tmp_path)
        elif os.sep == '/' and ':\\' in tmp_path:
            # platform is Linux and path is Windows, then convert to Linux path
            logger.debug('Platform is Linux but Paths are Windows. Converting paths to Linux paths')
            tmp_path = tmp_path.split('\\')
            tmp_path[0] = tmp_path[0].lower().replace(':', '')
            tmp_path = '/mnt/' + '/'.join(tmp_path)
        else:
            tmp_path = tmp_path.replace('/', os.sep).replace('\\', os.sep) # make sure the separator is correct

        downloader_config['download_dir'] = tmp_path

        # search in an infinite loop till you get your series
        target_series = search_and_select_series(series_name_predef, series_year_predef)
        logger.info(f'Selected series: {target_series}')

        # fetch episode links
        logger.info(f'Fetching episodes list')
        print(f'\nAvailable Episodes Details:', end=' ')
        episodes = client.fetch_episodes_list(target_series)
        print(f'{len(episodes)} episodes found.')

        if len(episodes) == 0:
            print('No episodes found in selected series! Exiting.')
            exit(0)

        logger.info(f'Displaying episodes list')
        client.show_episode_results(episodes, episodes_predef)

        # get user inputs
        if episodes_predef:
            print(f'\nUsing Predefined Input for episodes to download: {episodes_predef}')
            ep_range = episodes_predef
        else:
            default_ep_range = f"{episodes[0]['episode']}-{episodes[-1]['episode']}"
            ep_range = input(f"\nEnter episodes to download (ex: 1-16) [default={default_ep_range}]: ") or "all"
            if str(ep_range).lower() == 'all':
                ep_range = default_ep_range

        logger.debug(f'Selected episode range: {ep_range = }')

        try:
            ep_start, ep_end = map(float, ep_range.split('-'))
        except ValueError as ve:
            ep_start = ep_end = float(ep_range)

        # filter required episode links and print
        logger.info(f'Fetching episodes between {ep_start = } and {ep_end = }')
        print("\nFetching Episodes & Available Resolutions:")
        target_ep_links = client.fetch_episode_links(episodes, ep_start, ep_end)
        logger.debug(f'Fetched episodes: {target_ep_links}')
        # client.show_episode_links(target_ep_links)

        if len(target_ep_links) == 0:
            logger.error("No episodes are available for download! Exiting.")
            exit(0)

        # set output names & make it windows safe
        logger.debug(f'Set output names based on {target_series}')
        series_title, episode_prefix = client.set_out_names(target_series)
        logger.debug(f'{series_title = }, {episode_prefix = }')

        # set target output dir
        downloader_config['download_dir'] = os.path.join(f"{downloader_config['download_dir']}", f"{series_title}")
        logger.debug(f"Final download dir: {downloader_config['download_dir']}")

        # get available resolutions
        valid_resolutions = []
        valid_resolutions_gen = get_resolutions(target_ep_links.values())
        for _valid_res in valid_resolutions_gen:
            valid_resolutions = _valid_res
            if len(valid_resolutions) > 0:
                break   # get the resolutions from the first non-empty episode
        else:
            # set to default if empty
            valid_resolutions = ['360','480','720','1080']

        logger.debug(f'{valid_resolutions = }')

        # get valid resolution from user
        if resolution_predef:
            print(f'\nUsing Predefined Input for resolution: {resolution_predef}')
            resolution = resolution_predef
        else:
            resolution = input(f"\nEnter download resolution ({'|'.join(valid_resolutions)}) [default=720]: ") or "720"

        logger.info(f'Selected download resolution: {resolution}')

        # get m3u8 link for the specified resolution
        logger.info('Fetching m3u8 links for selected episodes')
        print('\nFetching Episode links:')
        target_dl_links = client.fetch_m3u8_links(target_ep_links, resolution, episode_prefix)
        available_dl_count = len([ k for k, v in target_dl_links.items() if v.get('downloadLink') is not None ])
        logger.debug(f'{target_dl_links = }, {available_dl_count = }')

        if len(target_dl_links) == 0:
            logger.error('No episodes available to download! Exiting.')
            exit(0)

        msg = f'Episodes available for download [{available_dl_count}/{len(target_dl_links)}].'; print(f'\n{msg}', end=' ')
        if start_download_predef:
            print(f'Using Predefined Input for start download: {start_download_predef}')
            proceed = 'y'
        elif available_dl_count == 0:
            proceed = 'y'       # print download summary directly if no episodes available for download
        else:
            proceed = input(f"Proceed to download (y|n)? ").lower() or 'y'

        logger.info(f'{msg} Proceed to download? {proceed}')

        if proceed == 'y':
            msg = f"Downloading episode(s) to {downloader_config['download_dir']}..."
            logger.info(msg); print(f"\n{msg}")
            # invoke downloader using a threadpool
            logger.info(f'Invoking batch downloader with {max_parallel_downloads = }')
            batch_downloader(downloader, target_dl_links, downloader_config, max_parallel_downloads)
        else:
            logger.error("Download halted on user input")

    except KeyboardInterrupt as ki:
        logger.error('User interrupted')
        exit(0)

    except Exception as e:
        logger.error(f'Error occurred: {e}. Check log for more details.')
        logger.warning(f'Stacktrace: {traceback.format_exc()}')
        exit(1)

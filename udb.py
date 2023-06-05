__version__ = '2.7'
__author__ = 'Prudhvi PLN'

import argparse
import os
import yaml

from Clients.AnimeClient import AnimeClient
from Clients.DramaClient import DramaClient
from Utils.HLSDownloader import downloader
from Utils.commons import threaded


# load yaml config into dict
def load_yaml(config_file):
    if not os.path.isfile(config_file):
        print(f'Config file [{config_file}] not found')
        exit(1)

    with open(config_file, "r") as stream:
        try:
            return yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(f"Error occured while reading yaml file: {exc}")
            exit(1)

def get_series_type(keys, predefined_input=None):
    types = {}
    print('\nSelect type of series:')
    for idx, typ in enumerate(keys):
        if typ != 'DownloaderConfig':
            print(f'{idx+1}: {typ.capitalize()}')
            types[idx+1] = typ

    if predefined_input:
        print(f'\nUsing Predefined Input: {predefined_input}')
        series_type = predefined_input
    else:
        series_type = int(input('\nEnter your choice: '))

    if series_type not in types:
        raise Exception('Invalid input!')
    else:
        return types[series_type]

def search_and_select_series(predefined_search_input=None, predefined_year_input=None):
    while True:
        # get search keyword from user input
        if predefined_search_input:
            print(f'\nUsing Predefined Input for search: {predefined_search_input}')
            keyword = predefined_search_input
        else:
            keyword = input("\nEnter series/movie name: ")

        # search with keyword and show results
        print("\nSearch Results:")
        search_results = client.search(keyword)

        if search_results is None or len(search_results) == 0:
            print('No matches found. Try with different keyword')
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
            print("Invalid input!"); exit(1)

        if option < 0 or option > len(search_results):
            print("Invalid option!"); exit(1)
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
        yield [ next(iter(i)) for i in item ]

def batch_downloader(download_fn, links, dl_config, max_parallel_downloads):

    @threaded(max_parallel=max_parallel_downloads, thread_name_prefix='udb-', print_status=False)
    def start_download(link, dl_config):
        return download_fn(link, dl_config)

    dl_status = start_download(links.values(), dl_config)
    # show download status at the end, so that progress bars are not disturbed
    print("\033[K") # Clear to the end of line
    width = os.get_terminal_size().columns
    print('\u2500' * width)
    print('Download Summary:', end='')
    status_str = ''
    for status in dl_status:
        status_str += f'\n{status}'
    # Once chatGPT suggested me to reduce 'print' usage as it involves IO to stdout
    print(status_str)
    print('\u2500' * width)


if __name__ == '__main__':
    try:
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

        # get series type
        series_type = get_series_type(config.keys(), series_type_predef)

        # create client
        if 'anime' in series_type.lower():
            client = AnimeClient(config[series_type])
        else:
            client = DramaClient(config[series_type])

        # set respective download dir if present
        if 'download_dir' in config[series_type]:
            downloader_config['download_dir'] = config[series_type]['download_dir']

        # modify path based on platform
        tmp_path = downloader_config['download_dir']
        if os.sep == '\\' and '/mnt/' in tmp_path:
            # platform is Windows and path is Linux, then convert to Windows path
            tmp_path = tmp_path.split('/')[2:]
            tmp_path[0] = tmp_path[0].upper() + ':'
            tmp_path = '\\'.join(tmp_path)
        elif os.sep == '/' and ':\\' in tmp_path:
            # platform is Linux and path is Windows, then convert to Linux path
            tmp_path = tmp_path.split('\\')
            tmp_path[0] = tmp_path[0].lower().replace(':', '')
            tmp_path = '/mnt/' + '/'.join(tmp_path)
        else:
            tmp_path = tmp_path.replace('/', os.sep).replace('\\', os.sep) # make sure the separator is correct

        downloader_config['download_dir'] = tmp_path

        # search in an infinite loop till you get your series
        target_series = search_and_select_series(series_name_predef, series_year_predef)

        # fetch episode links
        print('\nAvailable Episodes Details:')
        episodes = client.fetch_episodes_list(target_series)
        client.show_episode_results(episodes)

        # get user inputs
        if episodes_predef:
            print(f'\nUsing Predefined Input for episodes to download: {episodes_predef}')
            ep_range = episodes_predef
        else:
            ep_range = input("\nEnter episodes to download (ex: 1-16) [default=ALL]: ") or "all"
        if str(ep_range).lower() == 'all':
            ep_range = f"{episodes[0]['episode']}-{episodes[-1]['episode']}"

        try:
            ep_start, ep_end = map(int, ep_range.split('-'))
        except ValueError as ve:
            ep_start = ep_end = int(ep_range)

        # filter required episode links and print
        print("\nFetching Episodes & Available Resolutions:")
        target_ep_links = client.fetch_episode_links(episodes, ep_start, ep_end)
        # client.show_episode_links(target_ep_links)

        if len(target_ep_links) == 0:
            print("No episodes are available for download!")
            exit(0)

        # set output names & make it windows safe
        series_title, episode_prefix = client.set_out_names(target_series)
        # set target output dir
        downloader_config['download_dir'] = os.path.join(f"{downloader_config['download_dir']}", f"{series_title}")

        # get available resolutions
        valid_resolutions = []
        valid_resolutions_gen = get_resolutions(target_ep_links.values())
        for _valid_res in valid_resolutions_gen:
            valid_resolutions = _valid_res
            if len(valid_resolutions) > 0:
                break
        else:
            # set to default if empty
            valid_resolutions = ['360','480','720','1080']

        # get valid resolution from user
        while True:
            if resolution_predef:
                print(f'\nUsing Predefined Input for resolution: {resolution_predef}')
                resolution = resolution_predef
            else:
                resolution = input(f"\nEnter download resolution ({'|'.join(valid_resolutions)}) [default=720]: ") or "720"
            if resolution not in valid_resolutions:
                print(f'Invalid Resolution [{resolution}] entered! Please give a valid resolution!')
                resolution_predef = None    #reset predefined input if specified is not found
            else:
                break

        # get m3u8 link for the specified resolution
        print('\nFetching Episode links:')
        target_dl_links = client.fetch_m3u8_links(target_ep_links, resolution, episode_prefix)

        if len(target_dl_links) == 0:
            print('No episodes available to download! Exiting.')
            exit(0)

        if start_download_predef:
            print(f'\nUsing Predefined Input for start download: {start_download_predef}')
            proceed = 'y'
        else:
            proceed = input(f"\nProceed with downloading {len(target_dl_links)} episodes (y|n)? ").lower() or 'y'
        if proceed == 'y':
            print(f"\nDownloading episode(s) to {downloader_config['download_dir']}...")
            # invoke downloader using a threadpool
            batch_downloader(downloader, target_dl_links, downloader_config, max_parallel_downloads)
        else:
            print("Download halted on user input")

    except KeyboardInterrupt as ki:
        print('User interrupted')
        exit(0)

    # except Exception as e:
    #     print(f'Error occured: {e}')
    #     exit(1)

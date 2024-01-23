__author__ = 'Prudhvi PLN'

import re
from urllib.parse import quote_plus

from Clients.BaseClient import BaseClient


class GogoAnimeClient(BaseClient):
    '''Anime Client for GogoAnime site'''
    # step-0
    def __init__(self, config, session=None):
        super().__init__(config['request_timeout'], session)
        self.base_url = config['base_url']
        self.search_url = self.base_url + config['search_url']
        self.episodes_list_url = config['episodes_list_url']
        self.episodes_list_id_element = config['episodes_list_id_element']
        self.search_title_element = config['search_title_element']
        self.search_link_element = config['search_link_element']
        self.series_info_element = config['series_info_element']
        self.episode_list_element = config['episode_list_element']
        self.episode_link_element = config['episode_link_element']
        self.episode_sub_type_element = config['episode_sub_type_element']
        self.stream_links_element = config['stream_links_element']
        self.download_fetch_link = config['download_fetch_link']
        self.preferred_urls = config['preferred_urls'] if config['preferred_urls'] else []
        self.blacklist_urls = config['blacklist_urls'] if config['blacklist_urls'] else []
        self.selector_strategy = config.get('alternate_resolution_selector', 'lowest')
        self.logger.debug(f'GogoAnime client initialized with {config = }')
        # regex to fetch the encrypted url args required to fetch master m3u8 / download links
        self.ENCRYPTED_URL_ARGS_REGEX = re.compile(rb'data-value="(.+?)"')
        # regex to fetch key & iv for decryption & encrytion. Reference: https://github.com/justfoolingaround/animdl
        self.CRYPT_KEYS_REGEX = re.compile(rb"(?:container|videocontent)-(\d+)")

    # step-1.1
    def _get_series_info(self, link):
        '''
        get metadata of anime
        '''
        meta = {}
        soup = self._get_bsoup(link)
        # self.logger.debug(f'bsoup response for {link = }: {soup}')
        for detail in soup.select(self.series_info_element):
            line = detail.text.strip()
            if ':' in line:
                meta[line.split(':')[0].strip()] = line.split(':')[1].strip().split('\n')[0]

        # get the first & last episode number
        first_ep_no = soup.select_one(self.episode_list_element).text.split('-')[0].strip()
        last_ep_no = soup.select(self.episode_list_element)[-1].text.split('-')[-1].strip()
        meta['ep_start'], meta['ep_end'] = first_ep_no, last_ep_no
        # append '+' to indicate if series is still running
        meta['Episodes'] = f'{last_ep_no}+' if meta['Status'].lower() != 'completed' else last_ep_no

        # get anime id, which is used later to fetch episodes list
        meta['anime_id'] = soup.select_one(self.episodes_list_id_element)['value']

        return meta

    # step-1.2
    def _show_search_results(self, key, details):
        '''
        pretty print anime results based on your search
        '''
        line = f"{key}: {details.get('title')} | {details.get('Type')} | Genre: {details.get('Genre')}" + \
                f"\n   | Episodes: {details.get('Episodes', 'N/A')} | Released: {details.get('year')} | Status: {details.get('Status')}"
        print(line)

    # step-4.3
    def _show_episode_links(self, key, details):
        '''
        pretty print episode links from fetch_episode_links
        '''
        info = f"Episode: {self._safe_type_cast(key)}"
        if 'error' in details:
            info += f' | {details["error"]}'
            self.logger.error(info)
            return

        for _res, _vals in details.items():
            info += f' | {_res}P ({_vals["resolution_size"]})' #| URL: {_vals["downloadLink"]}

        print(info)

    # step-1
    def search(self, keyword, search_limit=10):
        '''
        search for anime based on a keyword
        '''
        # url encode the search word
        search_key = quote_plus(keyword)
        search_url = self.search_url + search_key
        soup = self._get_bsoup(search_url)

        # get matched items. Limit the search results to be displayed.
        search_titles = [ i.text for i in soup.select(self.search_title_element) ][:search_limit]
        search_links = [ i['href'] for i in soup.select(self.search_link_element) ][:search_limit]

        idx = 1
        search_results = {}
        for title, link in zip(search_titles, search_links):
            if link.startswith('/'):
                link = self.base_url + link
            item = {'title': title, 'link': link}
            # get every search result details
            item.update(self._get_series_info(link))
            item['year'] = item['Released']
            # add index to every search result
            search_results[idx] = item
            self._show_search_results(idx, item)
            idx += 1

        return search_results

    # step-2
    def fetch_episodes_list(self, target):
        '''
        fetch all available episodes list in the selected anime
        '''
        all_episodes_list = []
        list_episodes_url = self.episodes_list_url.replace('_ep_start_', target['ep_start']).replace('_ep_end_', target['ep_end']) + target['anime_id']

        self.logger.debug(f'Fetching soup to extract episodes from {list_episodes_url = }')
        soup = self._get_bsoup(list_episodes_url)

        # create list of dict of episode links
        self.logger.debug(f'Extracting episodes details to create list of dict')
        ep_sub_types = soup.select(self.episode_sub_type_element)
        ep_links = soup.select(self.episode_link_element)

        for sub_type, link in zip(ep_sub_types, ep_links):
            ep_link = link['href'].strip()
            if ep_link.startswith('/'):
                ep_link = self.base_url + ep_link
            ep_no = link.select_one('div.name').text.strip().split()[-1]
            all_episodes_list.append({
                'episode': float(ep_no) if '.' in ep_no else int(ep_no),
                'episodeLink': ep_link,
                'episodeSubs': sub_type.text.strip().capitalize()
            })

        return all_episodes_list[::-1]   # return episodes in ascending

    # step-3
    def show_episode_results(self, items, predefined_range):
        '''
        pretty print episodes list from fetch_episodes_list
        '''
        start, end = self._get_episode_range_to_show(items[0].get('episode'), items[-1].get('episode'), predefined_range, threshold=30)

        for item in items:
            if item.get('episode') >= start and item.get('episode') <= end:
                print(f"Episode: {self._safe_type_cast(item.get('episode'))} | Subs: {item.get('episodeSubs')}")

    # step-4
    def fetch_episode_links(self, episodes, ep_start, ep_end):
        '''
        fetch only required episodes based on episode range provided
        '''
        download_links = {}
        for episode in episodes:
            # self.logger.debug(f'Current {episode = }')

            if float(episode.get('episode')) >= ep_start and float(episode.get('episode')) <= ep_end:
                self.logger.debug(f'Processing {episode = }')

                self.logger.debug(f'Fetching stream link')
                link = self._get_stream_link(episode.get('episodeLink'), self.stream_links_element)
                self.logger.debug(f'Extracted stream link: {link = }')

                if link is not None:
                    # add episode details & stream link to udb dict
                    self._update_udb_dict(episode.get('episode'), episode)
                    self._update_udb_dict(episode.get('episode'), {'streamLink': link, 'refererLink': link})

                    self.logger.debug(f'Extracting m3u8 links for {link = }')
                    gdl_config = {
                        'link': link,
                        'crypt_keys_regex': self.CRYPT_KEYS_REGEX,
                        'encrypted_url_args_regex': self.ENCRYPTED_URL_ARGS_REGEX,
                        'download_fetch_link': self.download_fetch_link,
                        'preferred_urls': self.preferred_urls,
                        'blacklist_urls': self.blacklist_urls
                    }
                    m3u8_links = self._get_download_links(**gdl_config)
                    self.logger.debug(f'Extracted {m3u8_links = }')

                    download_links[episode.get('episode')] = m3u8_links
                    self._show_episode_links(episode.get('episode'), m3u8_links)

        return download_links

    # step-5
    def set_out_names(self, target_series):
        anime_title = self._windows_safe_string(target_series['title'])
        # set target output dir
        target_dir = f"{anime_title} ({target_series['year']})"
        series_typ = target_series.get('Type')
        anime_type = 'Episode' if 'series' in series_typ.lower() or 'anime' in series_typ.lower() else series_typ
        episode_prefix = f"{anime_title} {anime_type}"

        return target_dir, episode_prefix

    # step-6
    def fetch_m3u8_links(self, target_links, resolution, episode_prefix):
        '''
        return dict containing m3u8 links based on resolution
        '''
        _get_ep_name = lambda resltn: f"{episode_prefix} {ep} - {resltn}P.mp4"

        for ep, link in target_links.items():
            error = None
            self.logger.debug(f'Epsiode: {ep}, Link: {link}')
            info = f'Episode: {self._safe_type_cast(ep)} |'

            # select the resolution based on the selection strategy
            selected_resolution = self._resolution_selector(link.keys(), resolution, self.selector_strategy)
            res_dict = link.get(selected_resolution)
            self.logger.debug(f'{selected_resolution = } based on {self.selector_strategy = }, Data: {res_dict = }')

            if 'error' in link:
                error = link.get('error')

            elif res_dict is None or len(res_dict) == 0:
                error = f'Resolution [{resolution}] not found'

            else:
                info = f'{info} {selected_resolution}P |'
                try:
                    ep_name = _get_ep_name(selected_resolution)
                    ep_link = res_dict['downloadLink']
                    link_type = res_dict['downloadType']

                    # add download link and it's type against episode
                    self._update_udb_dict(ep, {'episodeName': ep_name, 'downloadLink': ep_link, 'downloadType': link_type})
                    self.logger.debug(f'{info} Link found [{ep_link}]')
                    print(f'{info} Link found [{ep_link}]')

                except Exception as e:
                    error = f'Failed to fetch link with error [{e}]'

            if error:
                # add error message and log it
                ep_name = _get_ep_name(resolution)
                self._update_udb_dict(ep, {'episodeName': ep_name, 'error': error})
                self.logger.error(f'{info} {error}')

        final_dict = { k:v for k,v in self._get_udb_dict().items() }

        return final_dict

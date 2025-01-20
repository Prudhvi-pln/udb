__author__ = 'Prudhvi PLN'

import re
from urllib.parse import quote_plus

from Clients.BaseClient import BaseClient


class KissKhClient(BaseClient):
    '''
    Drama Client for kisskh site
    '''
    # step-0
    def __init__(self, config, session=None):
        self.base_url = config.get('base_url', 'https://kisskh.co/')
        self.search_url = self.base_url + config.get('search_url', 'api/DramaList/Search?q=')
        self.series_url = self.base_url + config.get('series_url', 'api/DramaList/Drama/')
        self.episode_url = self.base_url + config.get('episode_url', 'api/DramaList/Episode/')
        self.subtitles_url = self.base_url + config.get('subtitles_url', 'api/Sub/')
        self.preferred_urls = config['preferred_urls'] if config.get('preferred_urls') else []
        self.blacklist_urls = config['blacklist_urls'] if config.get('blacklist_urls') else []
        self.selector_strategy = config.get('alternate_resolution_selector', 'lowest')
        self.hls_size_accuracy = config.get('hls_size_accuracy', 0)
        super().__init__(config.get('request_timeout', 30), session)
        self.logger.debug(f'KissKh Drama client initialized with {config = }')

    # step-1.1
    def _show_search_results(self, key, details):
        '''
        pretty print drama results based on your search
        '''
        line = f"{key}: {details.get('title')} | Country: {details.get('country')}" + \
                f"\n   | Episodes: {details.get('episodesCount', 'NA')} | Released: {details.get('year')} | Status: {details.get('status')}"
        self._colprint('results', line)

    # step-1
    def search(self, keyword, search_limit=5):
        '''
        search for drama based on a keyword
        '''
        # search type codes
        search_types = {
            # '0': 'all',
            '1': 'Asian Drama',
            '2': 'Asian Movies',
            '3': 'Anime',
            '4': 'Hollywood'
        }
        idx = 1
        search_results = {}
        search_type = None

        # check if search type is provided
        try:
            if '>' in keyword:
                search_type = [ k for k,v in search_types.items() if keyword.split('>')[0].strip().lower() in v.lower() ][0]
                keyword = keyword.split('>')[1].strip()
                search_limit = search_limit * 2
        except:
            pass

        # url encode search keyword
        search_key = quote_plus(keyword)

        for code, type in search_types.items():
            if search_type and search_type != code:
                continue
            self._colprint('blurred', f"-------------- {type} --------------")
            self.logger.debug(f'Searching for {type} with keyword: {keyword}')
            search_url = self.search_url + search_key + '&type=' + str(code)
            search_data = self._send_request(search_url, return_type='json')[:search_limit]
            # if len(search_data) == 0:
            #     self.logger.error('Nothing here')

            # Get basic details available from the site
            for result in search_data:
                series_id = result['id']
                self.logger.debug(f'Fetching additional details for series_id: {series_id}')
                series_data = self._send_request(self.series_url + str(series_id), return_type='json')
                item = {
                    'title': series_data['title'],
                    'series_id': series_id,
                    'country': series_data['country'],
                    'episodesCount': series_data['episodesCount'],
                    'series_type': series_data['type'],
                    'status': series_data['status'],
                    'episodes': series_data['episodes']
                }
                try:
                    item['year'] = series_data['releaseDate'].split('-')[0]
                except:
                    item['year'] = 'XXXX'

                # Add index to every search result
                search_results[idx] = item
                self._show_search_results(idx, item)
                idx += 1

        return search_results

    # step-2
    def fetch_episodes_list(self, target):
        '''
        fetch episode links as dict containing link, name
        '''
        all_episodes_list = []
        episodes = target['episodes']

        self.logger.debug(f'Extracting episode details for {target["title"]}')
        for episode in episodes:
            ep_no = int(episode['number']) if str(episode['number']).endswith('.0') else episode['number']
            ep_name = f"{target['title']} Episode {ep_no}"
            all_episodes_list.append({
                'episode': ep_no,
                'episodeName': self._windows_safe_string(ep_name),
                'episodeId': episode['id'],
                'episodeSubs': episode['sub']
            })

        return all_episodes_list[::-1]   # return episodes in ascending

    # step-3
    def show_episode_results(self, items, *predefined_range):
        '''
        pretty print episodes list from fetch_episodes_list
        '''
        start, end = self._get_episode_range_to_show(items[0].get('episode'), items[-1].get('episode'), predefined_range[1], threshold=24)

        for item in items:
            if item.get('episode') >= start and item.get('episode') <= end:
                fmted_name = re.sub(r'\b(\d$)', r'0\1', item.get('episodeName'))
                self._colprint('results', f"Episode: {fmted_name}")

    # step-4
    def fetch_episode_links(self, episodes, ep_ranges):
        '''
        fetch only required episodes based on episode range provided
        '''
        download_links = {}
        ep_start, ep_end, specific_eps = ep_ranges['start'], ep_ranges['end'], ep_ranges.get('specific_no', [])

        for episode in episodes:
            # self.logger.debug(f'Current {episode = }')

            if (float(episode.get('episode')) >= ep_start and float(episode.get('episode')) <= ep_end) or (float(episode.get('episode')) in specific_eps):
                self.logger.debug(f'Processing {episode = }')

                self.logger.debug(f'Fetching stream link')
                dl_links = self._send_request(self.episode_url + str(episode.get('episodeId')) + '.png', return_type='json')
                if dl_links is None:
                    self.logger.warning(f'Failed to fetch stream link for episode: {episode.get("episode")}')
                    continue
                link = dl_links.get('Video')
                self.logger.debug(f'Extracted stream link: {link = }')

                # skip if no stream link found
                if link is None:
                    continue

                # add episode details & stream link to udb dict
                self._update_udb_dict(episode.get('episode'), episode)
                self._update_udb_dict(episode.get('episode'), {'streamLink': link})

                # get subtitles dictionary (key:value = language:link) and add to udb dict
                if episode.get('episodeSubs', 0) > 0:
                    self.logger.debug(f'Subtitles found. Fetching subtitles for the episode...')
                    subtitles = self._send_request(self.subtitles_url + str(episode.get('episodeId')), return_type='json')
                    subtitles = { sub['label']: sub['src'] for sub in subtitles }
                    self._update_udb_dict(episode.get('episode'), {'subtitles': subtitles})

                # get actual download links
                m3u8_links = [{'file': link, 'type': 'hls'}] if link.endswith('.m3u8') else [{'file': link, 'type': 'mp4'}]
                self.logger.debug(f'Fetching resolution streams from the stream link...')
                m3u8_links = self._get_download_links(m3u8_links, None, self.preferred_urls, self.blacklist_urls)
                self.logger.debug(f'Extracted {m3u8_links = }')

                download_links[episode.get('episode')] = m3u8_links
                self._show_episode_links(episode.get('episode'), m3u8_links)

        return download_links

    # step-5
    def set_out_names(self, target_series):
        drama_title = self._windows_safe_string(target_series['title'])
        # set target output dir
        target_dir = drama_title if drama_title.endswith(')') else f"{drama_title} ({target_series['year']})"

        return target_dir, None

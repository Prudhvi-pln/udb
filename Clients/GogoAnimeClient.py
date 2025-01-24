__author__ = 'Prudhvi PLN'

import re
from urllib.parse import quote_plus

from Clients.BaseClient import BaseClient


class GogoAnimeClient(BaseClient):
    '''
    Anime Client for GogoAnime site
    '''
    # step-0
    def __init__(self, config, session=None):
        self.base_url = config.get('base_url', 'https://anitaku.to/')
        self.search_url = self.base_url + config.get('search_url', 'search.html?keyword=')
        self.episodes_list_url = config.get('episodes_list_url', 'ajax/load-list-episode?ep_start={ep_start}&ep_end={ep_end}&id=')
        self.episodes_list_id_element = config.get('episodes_list_id_element', 'div.anime_info_body input#movie_id')
        self.search_link_element = config.get('search_link_element', 'ul.items li p.name a')
        self.series_info_element = config.get('series_info_element', 'div.anime_info_body p.type')
        self.episode_list_element = config.get('episode_list_element', 'ul#episode_page li a')
        self.episode_link_element = config.get('episode_link_element', 'ul#episode_related li a')
        self.episode_sub_type_element = config.get('episode_sub_type_element', 'ul#episode_related li a div.cate')
        self.stream_links_element = config.get('stream_links_element', 'div.anime_muti_link a')
        self.download_fetch_link = config.get('download_fetch_link', 'encrypt-ajax.php')
        self.preferred_urls = config['preferred_urls'] if config.get('preferred_urls') else []
        self.blacklist_urls = config['blacklist_urls'] if config.get('blacklist_urls') else []
        self.selector_strategy = config.get('alternate_resolution_selector', 'lowest')
        self.hls_size_accuracy = config.get('hls_size_accuracy', 0)
        super().__init__(config.get('request_timeout', 30), session)
        self.logger.debug(f'GogoAnime client initialized with {config = }')
        # regex to fetch the encrypted url args required to fetch master m3u8 / download links
        self.ENCRYPTED_URL_ARGS_REGEX = re.compile(rb'data-value="(.+?)"')
        # regex to fetch key & iv for decryption & encrytion. Reference: https://github.com/justfoolingaround/animdl
        self.CRYPT_KEYS_REGEX = re.compile(rb"(?:container|videocontent)-(\d+)")
        self.CDN_BASE_URL_REGEX = "base_url_cdn_api = '(.*)'"
        self._colprint('blinking', '\nWARNING: This site has no updates after November 24, 2024. For latest episodes, use the other site.')

    # step-1.1
    def _get_series_info(self, link):
        '''
        get metadata of anime
        '''
        meta = {}
        soup = self._get_bsoup(link)
        # self.logger.debug(f'bsoup response for {link = }: {soup}')
        if soup is None:
            return None

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

        # get the load list url dynamically
        try:
            meta['base_url_cdn_api'] = re.search(self.CDN_BASE_URL_REGEX, soup.find(string=re.compile(self.CDN_BASE_URL_REGEX))).group(1)
        except:
            raise Exception('Failed to find base_url_cdn_api!')

        return meta

    # step-1.2
    def _show_search_results(self, key, details):
        '''
        pretty print anime results based on your search
        '''
        line = f"{key}: {details.get('title')} | {details.get('Type')} | Genre: {details.get('Genre')}" + \
                f"\n   | Episodes: {details.get('Episodes', 'N/A')} | Released: {details.get('year')} | Status: {details.get('Status')}"
        self._colprint('results', line)

    # step-1
    def search(self, keyword, search_limit=10):
        '''
        search for anime based on a keyword
        '''
        # url encode the search word
        search_key = quote_plus(keyword)
        search_url = self.search_url + search_key
        soup = self._get_bsoup(search_url)

        idx = 1
        search_results = {}
        # get matched items. Limit the search results to be displayed.
        for element in soup.select(self.search_link_element)[:search_limit]:
            title = element.text
            link = element['href']
            if link.startswith('/'):
                link = self.base_url + link
            data = self._get_series_info(link)
            if data is not None:
                item = {'title': title, 'link': link}
                # get every search result details
                item.update(data)
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
        list_episodes_url = target['base_url_cdn_api'] + self.episodes_list_url.format(ep_start=target['ep_start'], ep_end=target['ep_end']) + target['anime_id']

        self.logger.debug(f'Fetching soup to extract episodes from {list_episodes_url = }')
        soup = self._get_bsoup(list_episodes_url)

        # create list of dict of episode links
        self.logger.debug(f'Extracting episodes details to create list of dict')
        ep_sub_types = soup.select(self.episode_sub_type_element)
        ep_links = soup.select(self.episode_link_element)

        # set episode prefix
        anime_title, series_typ = self._windows_safe_string(target['title']), target.get('Type')
        anime_type = 'Episode' if 'series' in series_typ.lower() or 'anime' in series_typ.lower() else series_typ

        for sub_type, link in zip(ep_sub_types, ep_links):
            ep_link = link['href'].strip()
            if ep_link.startswith('/'):
                ep_link = self.base_url + ep_link
            ep_no = link.select_one('div.name').text.strip().split()[-1]
            all_episodes_list.append({
                'episode': float(ep_no) if '.' in ep_no else int(ep_no),
                'episodeLink': ep_link,
                'episodeName': f"{anime_title} {anime_type} {ep_no}",
                'episodeSubs': sub_type.text.strip().capitalize()
            })

        return all_episodes_list[::-1]   # return episodes in ascending

    # step-3
    def show_episode_results(self, items, *predefined_range):
        '''
        pretty print episodes list from fetch_episodes_list
        '''
        start, end = self._get_episode_range_to_show(items[0].get('episode'), items[-1].get('episode'), predefined_range[1], threshold=30)

        for item in items:
            if item.get('episode') >= start and item.get('episode') <= end:
                self._colprint('results', f"Episode: {self._safe_type_cast(item.get('episode'))} | Subs: {item.get('episodeSubs')}")

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
                link = self._get_stream_link(episode.get('episodeLink'), self.stream_links_element)
                self.logger.debug(f'Extracted stream link: {link = }')

                # skip if no stream link found
                if link is None:
                    continue

                # add episode details & stream link to udb dict
                self._update_udb_dict(episode.get('episode'), episode)
                self._update_udb_dict(episode.get('episode'), {'streamLink': link, 'refererLink': link})

                self.logger.debug(f'Extracting m3u8 links for {link = }')
                gdl_config = {
                    'link': link,
                    'crypt_keys_regex': self.CRYPT_KEYS_REGEX,
                    'encrypted_url_args_regex': self.ENCRYPTED_URL_ARGS_REGEX,
                    'download_fetch_link': self.download_fetch_link
                }
                # get download sources
                m3u8_links = self._get_download_sources(**gdl_config)
                if 'error' not in m3u8_links:
                    # get actual download links
                    m3u8_links = self._get_download_links(m3u8_links, link, self.preferred_urls, self.blacklist_urls)
                self.logger.debug(f'Extracted {m3u8_links = }')

                download_links[episode.get('episode')] = m3u8_links
                self._show_episode_links(episode.get('episode'), m3u8_links)

        return download_links

    # step-5
    def set_out_names(self, target_series):
        anime_title = self._windows_safe_string(target_series['title'])
        # set target output dir
        target_dir = f"{anime_title} ({target_series['year']})"

        return target_dir, None

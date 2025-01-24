__author__ = 'Prudhvi PLN'

import re
from urllib.parse import quote_plus

from Clients.BaseClient import BaseClient


class AsianDramaClient(BaseClient):
    '''
    Drama Client for asianbxkiun site
    '''
    # step-0
    def __init__(self, config, session=None):
        self.base_url = config.get('base_url', 'https://asianbxkiun.pro/')
        self.search_url = self.base_url + config.get('search_url', 'search.html?keyword=')
        self.search_link_element = config.get('search_link_element', 'ul.items li a')
        self.series_info_element = config.get('series_info_element', 'div.video-details')
        self.mdl_search_link = config.get('mdl_search_link', 'https://mydramalist.com/search?adv=titles&ty=68,77,83,86&so=popular&q=')
        self.episode_link_element = config.get('episode_link_element', 'ul.items li a')
        self.episode_sub_type_element = config.get('episode_sub_type_element', 'ul.items li a div.type span')
        self.episode_upload_time_element = config.get('episode_upload_time_element', 'ul.items li a span.date')
        self.stream_links_element = config.get('stream_links_element', 'div.play-video iframe')
        self.download_fetch_link = config.get('download_fetch_link', 'encrypt-ajax.php')
        self.preferred_urls = config['preferred_urls'] if config.get('preferred_urls') else []
        self.blacklist_urls = config['blacklist_urls'] if config.get('blacklist_urls') else []
        self.selector_strategy = config.get('alternate_resolution_selector', 'lowest')
        self.hls_size_accuracy = config.get('hls_size_accuracy', 0)
        super().__init__(config.get('request_timeout', 30), session)
        self.logger.debug(f'Asian Drama client initialized with {config = }')
        # regex to fetch the encrypted url args required to fetch master m3u8 / download links
        self.ENCRYPTED_URL_ARGS_REGEX = re.compile(rb'data-value="(.+?)"')
        # key & iv for decryption & encrytion. Not sure how these are fetched :(
        # Reference: https://github.com/CoolnsX/dra-cla/blob/main/dra-cla
        self.__key = b'93422192433952489752342908585752'
        self.__iv = b'9262859232435825'
        self._colprint('blinking', '\nWARNING: This site has no updates after November 24, 2024. For latest episodes, use the other site.')

    # step-1.1
    def _get_series_info(self, link, year):
        '''
        get metadata of a drama
        '''
        meta = {}
        # If yeat is already present, no need to look further. If not, look into details.
        if year != 'XXXX':
            return meta
        soup = self._get_bsoup(link)
        # self.logger.debug(f'bsoup response for {link = }: {soup}')
        if soup is None:
            return meta

        details = soup.select_one(self.series_info_element)
        title = details.select_one('span.date').text.strip()
        try:
            year_match = re.search(r'\((\d{4})\)$', title)
            if year_match:
                year = year_match.group(1)
            else:
                year = re.search(r'\((\d{4})\)', details.text).group(1)
        except:
            year = 'XXXX'

        # if series is ongoing, get expected no of total episodes. works only for dramas where meta is available
        try:
            tot_eps = re.search('Episodes:(.*)', details.text).group(1).strip()
        except:
            tot_eps = None

        meta = {'year': year, 'total_episodes': tot_eps}

        return meta

    # step-1.2
    def _get_mdl_series_info(self, title, year):
        '''
        get extra information about a drama from MDL, optional
        '''
        # Extra information about the series from MDL, optional
        yr_search = f'&re={year},{year}' if year != 'XXXX' else ''
        mdl_link = self.mdl_search_link + quote_plus(title.replace(f' ({year})', '')) + yr_search

        self.logger.debug(f'Fetching extra information for series from MDL: {mdl_link}')
        soup_mdl = self._get_bsoup(mdl_link)
        selected_result = soup_mdl.select_one('div.box')     # Assuming first result is the correct one. This is where it could go wrong :(
        if selected_result.select_one('span.text-muted') is None:
            self.logger.warning(f'No extra information found in MDL for series: {title}')
            return {}

        series_type, extra_details = selected_result.select_one('span.text-muted').text.split(' - ')
        if year == 'XXXX': year = extra_details.split(', ')[0]
        tot_eps = '1' if 'movie' in series_type.lower() else extra_details.split(', ')[-1]
        rating = selected_result.select_one('span.score').text

        meta = {
            'series_type': series_type, 'year': year,
            'rating': rating, 'total_episodes': tot_eps
        }

        return meta

    # step-1.3
    def _show_search_results(self, key, details):
        '''
        pretty print drama results based on your search
        '''
        ep_details = details.get('last_episode') + '/' + details.get('total_episodes') if details.get('total_episodes') else details.get('last_episode')
        line = f"{key}: {details.get('title')} | Released: {details.get('year')} | Type: {details.get('series_type', 'N/A')} | MDL Rating: {details.get('rating', 'N/A')}" + \
             f"\n   | Episodes: {ep_details} | Last Upload: {details.get('last_episode_time', 'NA')}"
        self._colprint('results', line)

    # step-2.1
    def _get_episodes_list(self, soup):
        '''Extract episodes and return as a list'''
        episode_list = []

        sub_types = soup.select(self.episode_sub_type_element)
        upload_times = soup.select(self.episode_upload_time_element)
        links = soup.select(self.episode_link_element)

        # get episode links
        self.logger.debug(f'Extracting episodes details to create list of dict')
        for sub_typ, upload_time, link in zip(sub_types, upload_times, links):
            ep_link = link['href']
            if ep_link.startswith('/'):
                ep_link = self.base_url + ep_link
            ep_name = link.select_one('div.name').text.strip()
            ep_no = ep_name.split()[-1]
            ep_no = float(ep_no) if '.' in ep_no else int(ep_no)
            ep_upload_time = upload_time.text.strip()
            ep_sub_typ = sub_typ.text.strip().capitalize()
            episode_list.append({
                'episode': ep_no,
                'episodeName': self._windows_safe_string(ep_name),
                'episodeLink': ep_link,
                'episodeSubs': ep_sub_typ,
                'episodeUploadTime': ep_upload_time
            })

        return episode_list

    # step-1
    def search(self, keyword, search_limit=10):
        '''
        search for drama based on a keyword
        '''
        # url encode search keyword
        search_key = quote_plus(keyword)
        search_url = self.search_url + search_key
        soup = self._get_bsoup(search_url)

        # Get basic details available from the site
        links = soup.select(self.search_link_element)[:search_limit]
        titles = soup.select('div.name')
        last_ep_dates = soup.select('div.meta span')

        idx = 1
        search_results = {}
        # get matched items. Limit the search results to be displayed.
        for s_link, s_title, s_last_ep_date in zip(links, titles, last_ep_dates):
            link = s_link['href']
            if link.startswith('/'):
                link = self.base_url + link

            title = ' '.join(s_title.text.strip().split()[:-2])
            last_ep = s_title.text.strip().split()[-1]
            last_ep_date = s_last_ep_date.text.strip()

            try:
                year = re.search(r'\((\d{4})\)$', title).group(1)
            except:
                year = 'XXXX'
            # Add mandatory information
            item = {
                'title': title, 'year': year, 'link': link,
                'last_episode': last_ep, 'last_episode_time': last_ep_date
            }

            # Skip search result if it is already present. This happens becoz the search results are separate for SUB & RAW
            # Just need to compare with last obtained search result.
            if len(search_results) > 0 and search_results[idx-1]['title'] == item['title'] and (item['year'] == 'XXXX' or search_results[idx-1]['year'] == item['year']):
                continue

            # Add additional information, optional
            data = self._get_series_info(link, year)
            item.update(data)

            # Add more additional details from MDL
            data = self._get_mdl_series_info(title, item['year'])
            item.update(data)

            # Add index to every search result
            search_results[idx] = item
            self._show_search_results(idx, item)
            idx += 1

        return search_results

    # step-2
    def fetch_episodes_list(self, target):
        '''
        fetch episode links as dict containing link, name, upload time
        '''
        all_episodes_list = []
        series_link = target.get('link')
        self.logger.debug(f'Fetching soup to extract episodes from {series_link = }')

        soup = self._get_bsoup(series_link)
        all_episodes_list.extend(self._get_episodes_list(soup))

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
                self._colprint('results', f"Episode: {fmted_name} | Subs: {item.get('episodeSubs')} | Release date: {item.get('episodeUploadTime')}")

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
                    'encryption_key': self.__key,
                    'decryption_key': self.__key,
                    'iv': self.__iv,
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
        drama_title = self._windows_safe_string(target_series['title'])
        # set target output dir
        target_dir = drama_title if drama_title.endswith(')') else f"{drama_title} ({target_series['year']})"

        return target_dir, None

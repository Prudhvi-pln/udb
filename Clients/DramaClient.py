__author__ = 'Prudhvi PLN'

import re
from urllib.parse import quote_plus

from Clients.BaseClient import BaseClient


class DramaClient(BaseClient):
    '''
    Drama Client for MyAsianTV site
    '''
    # step-0
    def __init__(self, config, session=None):
        self.base_url = config.get('base_url', 'https://myasiantv.ac/')
        self.search_url = self.base_url + config.get('search_url', 'search.html?key=')
        self.episodes_list_url = self.base_url + config.get('episodes_list_url', 'ajax/episode-list/{series_name}/{pg_no}.html?page={pg_no}')
        self.search_link_element = config.get('search_link_element', 'ul.items li h2 a')
        self.series_info_element = config.get('series_info_element', 'div.left p')
        self.episode_link_element = config.get('episode_link_element', 'ul.list-episode li h2 a')
        self.episode_sub_type_element = config.get('episode_sub_type_element', 'ul.list-episode li img')
        self.episode_upload_time_element = config.get('episode_upload_time_element', 'ul.list-episode li span')
        self.stream_links_element = config.get('stream_links_element', 'div.anime_muti_link div')
        self.download_fetch_link = config.get('download_fetch_link', 'encrypt-ajax.php')
        self.preferred_urls = config['preferred_urls'] if config['preferred_urls'] else []
        self.blacklist_urls = config['blacklist_urls'] if config['blacklist_urls'] else []
        self.selector_strategy = config.get('alternate_resolution_selector', 'lowest')
        self.hls_size_accuracy = config.get('hls_size_accuracy', 0)
        super().__init__(config['request_timeout'], session)
        self.logger.debug(f'Drama client initialized with {config = }')
        # regex to fetch the encrypted url args required to fetch master m3u8 / download links
        self.ENCRYPTED_URL_ARGS_REGEX = re.compile(rb'data-value="(.+?)"')
        # key & iv for decryption & encrytion. Not sure how these are fetched :(
        # Reference: https://github.com/CoolnsX/dra-cla/blob/main/dra-cla
        self.__key = b'93422192433952489752342908585752'
        self.__iv = b'9262859232435825'

    # step-1.1
    def _get_series_info(self, link):
        '''
        get metadata of a drama
        '''
        meta = {}
        soup = self._get_bsoup(link)
        # self.logger.debug(f'bsoup response for {link = }: {soup}')
        if soup is None:
            return meta

        for detail in soup.select(self.series_info_element):
            line = detail.text.strip()
            if ':' in line:
                meta[line.split(':')[0].strip()] = line.split(':')[1].strip().split('\n')[0]

        # get last episode number
        last_ep_element = soup.select_one(self.episode_link_element)
        if last_ep_element is None:
            return meta

        last_ep_no = last_ep_element.text.strip().split()[-1]
        # if series is ongoing, get expected no of total episodes. works only for dramas where meta is available
        if meta['Status'].lower() != 'completed':
            try:
                match = re.search('Episodes:(.*)', soup.select('.info')[0].text)
                last_ep_no = f"{last_ep_no}+{'/' + match.group(1).strip() if match else ''}"
            except:
                last_ep_no = f'{last_ep_no}+'

        meta['Episodes'] = last_ep_no

        return meta

    # step-1.2
    def _show_search_results(self, key, details):
        '''
        pretty print drama results based on your search
        '''
        line = f"{key}: {details.get('title')} | Country: {details.get('Country')} | Genre: {details.get('Genre')}" + \
                f"\n   | Episodes: {details.get('Episodes', 'NA')} | Released: {details.get('year')} | Status: {details.get('Status')}"
        self._colprint('results', line)

    # step-2.1
    def _get_episodes_list(self, soup, ajax=False):
        '''Extract episodes and return as a list'''
        episode_list = []
        # if request is ajax, then use shortened css path, i.e., excluding 'ul'
        shortened_css = lambda x: ' '.join(x.split(' ')[1:]) if ajax else x

        sub_types = soup.select(shortened_css(self.episode_sub_type_element))
        upload_times = soup.select(shortened_css(self.episode_upload_time_element))
        links = soup.select(shortened_css(self.episode_link_element))

        # get episode links
        self.logger.debug(f'Extracting episodes details to create list of dict')
        for sub_typ, upload_time, link in zip(sub_types, upload_times, links):
            ep_link = link['href']
            if ep_link.startswith('/'):
                ep_link = self.base_url + ep_link
            ep_name = link.text.strip()
            ep_no = ep_name.split()[-1]
            ep_no = float(ep_no) if '.' in ep_no else int(ep_no)
            ep_upload_time = upload_time.text.strip()
            ep_sub_typ = sub_typ['src'].split('/')[-1].split('.')[0].capitalize()
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

        idx = 1
        search_results = {}
        # get matched items. Limit the search results to be displayed.
        for element in soup.select(self.search_link_element)[:search_limit]:
            title = element.text
            link = element['href']
            if link.startswith('/'):
                link = self.base_url + link

            # Add mandatory information
            item = {'title': title, 'link': link}

            # Add additional information
            data = self._get_series_info(link)
            item.update(data)
            item['year'] = item.get('Release year', 'XXXX')

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

        while soup.select('.paging'):
            self.logger.debug(f'Found more episodes')
            has_more = re.search("'(.*)','(.*)'", soup.select('.paging')[0]['onclick'])

            if not has_more:
                raise Exception('Show more element not found')
            pg_no, series = has_more.group(1), has_more.group(2)
            more_ep_link = self.episodes_list_url.format(series_name=series, pg_no=pg_no)

            self.logger.debug(f'Fetching more episodes for {series = } from {pg_no = }. URL: {more_ep_link}')
            soup = self._get_bsoup(more_ep_link, referer=series_link, extra_headers={'x-requested-with': 'XMLHttpRequest'})
            all_episodes_list.extend(self._get_episodes_list(soup, True))

        return all_episodes_list[::-1]   # return episodes in ascending

    # step-3
    def show_episode_results(self, items, *predefined_range):
        '''
        pretty print episodes list from fetch_episodes_list
        '''
        start, end = self._get_episode_range_to_show(items[0].get('episode'), items[-1].get('episode'), predefined_range[1], threshold=24)

        for item in items:
            if item.get('episode') >= start and item.get('episode') <= end:
                fmted_name = re.sub(r' (\d$)', r' 0\1', item.get('episodeName'))
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

                if link is not None:
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

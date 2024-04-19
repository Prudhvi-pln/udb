__author__ = 'Prudhvi PLN'

from urllib.parse import quote_plus

from Clients.BaseClient import BaseClient
from Clients.VidPlayClient import VidPlayClient


class VidSrcClient(BaseClient):
    '''
    Movies/Series Client using TheMovieDB & VidSrc APIs
    '''
    # step-0
    def __init__(self, config, session=None):
        self.base_url = config['base_url']
        self.search_url = self.base_url + config['search_url']
        self.search_link_element = config['search_link_element']
        self.series_info_element = config['series_info_element']
        vs_base_url = config['Vidsrc']['base_url']
        self.episodes_list_url = vs_base_url + config['Vidsrc']['episodes_list_url']
        self.episodes_list_element = config['Vidsrc']['episodes_list_element']
        self.sources_url = vs_base_url + config['Vidsrc']['sources_url']
        self.vidplay_source_url = vs_base_url + config['Vidsrc']['vidplay_source_url']
        self.preferred_urls = config['preferred_urls'] if config['preferred_urls'] else []
        self.blacklist_urls = config['blacklist_urls'] if config['blacklist_urls'] else []
        self.selector_strategy = config.get('alternate_resolution_selector', 'lowest')
        self.hls_size_accuracy = config.get('hls_size_accuracy', 0)
        super().__init__(config['request_timeout'], session)
        self.logger.debug(f'VidSrc client initialized with {config = }')
        # encryption key. Credits: https://github.com/Ciarands/vidsrc-to-resolver
        self.VIDSRC_KEY = 'WXrUARXb1aDLaZjI'
        # initialize VidPlay Client
        config['Vidplay']['request_timeout'] = config['request_timeout']
        self.vpc = VidPlayClient(config['Vidplay'], session)

    # step-1.1
    def _get_series_info(self, link):
        '''
        get metadata of movie/show
        '''
        meta = {}
        soup = self._get_bsoup(link)
        # self.logger.debug(f'bsoup response for {link = }: {soup}')

        for i in soup.select(self.series_info_element):
            k = i.get_text(':', strip=True)
            meta[k.split(':')[0]] = k.split(':')[-1]

        # add additional metadata. Metadata extraction elements are hardcoded. This may change depending on TMDB website.
        try:
            meta['genre'] = ', '.join([ i.text.strip() for i in soup.select('span.genres a') ])
            meta['score'] = soup.select_one('div.user_score_chart')['data-percent']
            meta['year'] = soup.select_one('span.release_date').text.strip().replace('(', '').replace(')', '')
            meta['runtime'] = soup.select_one('span.runtime').text.strip()
        except:
            pass

        # add tmdb id. required to retrieve data from VidSrc
        meta['show_id'] = link.split('?')[0].split('/')[-1].split('-')[0]
        # add type of series: TV-show or Movie
        meta['type'] = link.split('/')[-2].lower()
        # add count of seasons & episodes if it is a released series
        if meta['type'] == 'tv' and meta.get('year') is not None:
            try:
                # this is an extra api call just to fetch season and episode counts
                vidsrc_soup = self._get_bsoup(self.episodes_list_url.format(type=meta['type'], imdb_id=meta['show_id']), silent=True)
                seasons = len(vidsrc_soup.select(self.episodes_list_element))
                episodes = len(vidsrc_soup.select(self.episodes_list_element + ' li'))
                meta['seasons'], meta['episodes'] = seasons, episodes
            except:
                pass

        return meta

    # step-1.2
    def _show_search_results(self, key, details):
        '''
        pretty print the results based on your search
        '''
        line = f"{key}: {details.get('title')} | Language: {details.get('Original Language', 'N/A')} | Genre: {details.get('genre', 'N/A')}" + \
                f"\n   | Type: {'TV Show' if details.get('type') == 'tv' else details.get('type').capitalize()} | User Score: {details.get('score', '0')}% " + \
                f"| Released: {details.get('year', 'N/A')} | Status: {details.get('Status')}"

        if details.get('type').lower() == 'movie':
            line += f"\n   | Duration: {details.get('runtime', 'N/A')}"
        else:
            line += f"\n   | Seasons: {details.get('seasons', 'N/A')} | Total Episodes: {details.get('episodes', 'N/A')}"

        self._colprint('results', line)

    # step-3.1
    def get_season_ep_ranges(self, episodes):
        '''
        get episode ranges per season. Used for user selection
        '''
        ranges = {}
        self.logger.debug('Collecting episode ranges per season')
        for ep in episodes:
            season, ep_no = ep.get('season'), ep.get('episode')
            if season not in ranges:
                ranges[season] = {'start': ep_no, 'end': ep_no}
            else:
                ranges[season]['end'] = ep_no
        self.logger.debug(f'Episodes ranges per season: {ranges}')

        return ranges

    # step-4.1
    def _get_sources_ids(self, episode_id):
        '''
        extract the IDs of available sources
        '''
        sources = []
        # extract available sources
        sources_link = self.sources_url.format(episode_id=episode_id)
        self.logger.debug(f'Fetching sources [{sources_link}]')
        resp = self._send_request(sources_link, return_type='json')
        sources = resp['result']
        self.logger.debug(f'Extracted sources: {sources}')

        # extract vidplay source id from available sources
        try:
            sources = { src['title']: src['id'] for src in sources }
            self.logger.debug(f'Extracted source ids: {sources}')
        except Exception as e:
            self.logger.warning(f'Failed to extract source ids with error: {e}')

        return sources

    # step-1
    def search(self, keyword, search_limit=5):
        '''
        search for movie/show based on a keyword
        '''
        valid_types = ['movie', 'tv']
        # url encode the search word
        search_key = quote_plus(keyword)
        search_url = self.search_url + search_key + '&language=en-US'
        soup = self._get_bsoup(search_url)

        # get matched items. Limit the search results to be displayed.
        search_links = [ i for i in soup.select(self.search_link_element) if i['data-media-type'].lower() in valid_types ][:search_limit]

        idx = 1
        search_results = {}
        for element in search_links:
            title = element.text
            link = element['href']
            if link.startswith('/'):
                link = self.base_url + link
            item = {'title': title, 'link': link}
            # get every search result details
            item.update(self._get_series_info(link))
            # add index to every search result
            search_results[idx] = item
            self._show_search_results(idx, item)
            idx += 1

        return search_results

    # step-2
    def fetch_episodes_list(self, target):
        '''
        fetch all available episodes list in the selected show
        '''
        all_episodes_list = []
        list_episodes_url = self.episodes_list_url.format(type=target['type'], imdb_id=target['show_id'])

        self.logger.debug(f'Fetching soup to extract episodes from {list_episodes_url = }')
        soup = self._get_bsoup(list_episodes_url, silent=True)
        if soup is None:
            self.logger.error('Selected show not found in VidSrc catalog.')
            exit(1)

        # create list of dict of episode links
        self.logger.debug(f'Extracting episodes details to create list of dict')

        for element in soup.select(self.episodes_list_element):
            if target['type'] == 'tv':
                season = int(element['data-season'])
                self.logger.debug(f'Extracting episodes details for season: {season}')
            else:
                ep_no = 1   # only 1 element if it is a movie
                ep_name = target['title']

            for episode in element.select('li a'):
                episode_dict = {
                    'type': target['type'],
                    'episodeId': episode['data-id']
                }
                if target['type'] == 'tv':
                    ep_name = episode.text.strip().replace(':', ' -')
                    ep_no = int(ep_name.split()[1])
                    episode_dict['season'] = season

                episode_dict.update({
                    'episode': ep_no,
                    'episodeName': self._windows_safe_string(ep_name)
                })
                all_episodes_list.append(episode_dict)

        return sorted(all_episodes_list, key=lambda x: (x.get('season'), x['episode']))     # sort by seasons if exists and episodes

    # step-3
    def show_episode_results(self, items, *predefined_range):
        '''
        pretty print episodes list from fetch_episodes_list
        '''
        if items[0]['type'] == 'movie':
            for item in items:
                self._colprint('results', f"Movie: {item.get('episodeName')}")
            return

        # filter display range for seasons
        start, end = self._get_episode_range_to_show(items[0]['season'], items[-1]['season'], predefined_range[0], threshold=3, type='seasons')

        prev_season = None
        for item in items:
            cur_season = item.get('season')
            if cur_season >= start and cur_season <= end:
                if prev_season != cur_season:
                    self._colprint('results', f"-------------- Season: {cur_season} --------------")
                    prev_season = cur_season
                self._colprint('results', f"Season: {self._safe_type_cast(item.get('season'))} | {item.get('episodeName')}")

    # step-4
    def fetch_episode_links(self, episodes, ep_ranges):
        '''
        fetch only required episodes based on episode range provided
        '''
        download_links = {}
        series_flag, display_prefix = (True, 'Episode') if episodes[0]['type'] == 'tv' else (False, 'Movie')
        prev_season = None

        for episode in episodes:
            # self.logger.debug(f'Current {episode = }')
            season_no, ep_no = episode.get('season'), float(episode.get('episode'))
            if series_flag and season_no in ep_ranges:
                ep_start, ep_end, specific_eps = ep_ranges[season_no].get('start', 0), ep_ranges[season_no].get('end', 0), ep_ranges[season_no].get('specific_no', [])
                if prev_season != season_no:
                    self._colprint('results', f"-------------- Season: {season_no} --------------")
                    prev_season = season_no
            else:
                ep_start, ep_end, specific_eps = ep_ranges.get('start', 0), ep_ranges.get('end', 0), ep_ranges.get('specific_no', [])

            if (ep_no >= ep_start and ep_no <= ep_end) or (ep_no in specific_eps):
                self.logger.debug(f'Processing {episode = }')

                sources = self._get_sources_ids(episode.get('episodeId'))
                vidplay_src_id = sources.get('Vidplay')

                if vidplay_src_id:
                    vidplay_src_url = self.vidplay_source_url.format(vidplay_id=vidplay_src_id)
                    link = self.vpc._get_vidplay_link(vidplay_src_url, self.VIDSRC_KEY)
                else:
                    self.logger.warning('Vidplay source id not found in sources')
                    link = None

                if link is not None:
                    # udb key format: s + SEASON + e + EPISODE / m + MOVIE
                    udb_item_key = f"s{episode.get('season')}e{episode.get('episode')}" if series_flag else f"m{episode.get('episode')}"
                    # add episode details & vidplay link to udb dict
                    self._update_udb_dict(udb_item_key, episode)
                    self._update_udb_dict(udb_item_key, {'vidplayLink': link, 'refererLink': link})

                    self.logger.debug(f'Extracting m3u8 links for {link = }')
                    # get download sources
                    m3u8_links = self.vpc._resolve_sources(link)
                    # get subtitles dictionary (key:value = language:link) and add to udb dict
                    subtitles = self.vpc._get_vidplay_subtitles(link.split('?')[1])
                    self._update_udb_dict(udb_item_key, {'subtitles': subtitles})
                    if 'error' not in m3u8_links:
                        # get actual download links
                        m3u8_links = self._get_download_links(m3u8_links, link, self.preferred_urls, self.blacklist_urls)
                    self.logger.debug(f'Extracted {m3u8_links = }')

                    download_links[udb_item_key] = m3u8_links
                    self._show_episode_links(episode.get('episode'), m3u8_links, display_prefix)

        return download_links

    # step-5
    def set_out_names(self, target_series):
        show_title = self._windows_safe_string(target_series['title'])
        # set target output dir
        target_dir = f"{show_title} ({target_series['year']})"

        return target_dir, None

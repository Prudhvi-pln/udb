__author__ = 'Prudhvi PLN'

from Clients.BaseClient import BaseClient
from Clients.IMDBClient import IMDBClient
from Clients.TMDBClient import TMDBClient
from Clients.F2CloudClient import F2CloudClient


class VidSrcClient(BaseClient):
    '''
    Movies/Series Client using TheMovieDB/IMDB & VidSrc APIs
    '''
    # step-0
    def __init__(self, config, session=None):
        preferred_search = config.get('preferred_search', '')
        # pad the configuration with required keys
        config.setdefault('Vidsrc', {})
        config.setdefault('F2Cloud', {})
        vs_base_url = config['Vidsrc'].get('base_url', 'https://vidsrc.to/')
        self.episodes_list_url = vs_base_url + config['Vidsrc'].get('episodes_list_url', 'embed/{type}/{tmdb_id}')
        self.episodes_list_element = config['Vidsrc'].get('episodes_list_element', '.episodes')
        self.sources_url = vs_base_url + config['Vidsrc'].get('sources_url', 'ajax/embed/episode/{episode_id}/sources')
        self.provider_source_url = vs_base_url + config['Vidsrc'].get('provider_source_url', 'ajax/embed/source/{provider_id}')
        self.preferred_urls = config['preferred_urls'] if config['preferred_urls'] else []
        self.blacklist_urls = config['blacklist_urls'] if config['blacklist_urls'] else []
        self.selector_strategy = config.get('alternate_resolution_selector', 'lowest')
        self.hls_size_accuracy = config.get('hls_size_accuracy', 0)
        super().__init__(config['request_timeout'], session)

        # Initialize Search Client based on configuration
        config.setdefault('TMDB', {})
        config.setdefault('IMDB', {})
        config['TMDB']['request_timeout'] = config['request_timeout']
        config['IMDB']['request_timeout'] = config['request_timeout']
        if preferred_search.upper() == 'TMDB':
            self.search_client = TMDBClient(config['TMDB'], session)
        elif preferred_search.upper() == 'IMDB':
            self.search_client = IMDBClient(config['IMDB'], session)
        else:
            # If none specified, initialize Search Client based on reachability.
            # Prefer TMDB first, as IMDB changes a lot. Had to create IMDB client, because TMDB is blocked is certain networks.
            if TMDBClient.is_reachable():
                self.search_client = TMDBClient(config['TMDB'], session)
            else:
                self.logger.error('TMDB is not reachable. Using IMDB instead.')
                self.search_client = IMDBClient(config['IMDB'], session)

        self.logger.debug(f'VidSrc client initialized with {config = }')
        # Initialize F2Cloud Client
        config['F2Cloud']['request_timeout'] = config['request_timeout']
        self.provider_client = F2CloudClient(config['F2Cloud'], session)
        # Get F2Cloud's base encryption key
        self.ENCRYPTION_KEY = self.provider_client._get_key(True, 0)

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
        encoded_id = self.provider_client._encode_data(self.ENCRYPTION_KEY, episode_id)
        sources_link = self.sources_url.format(episode_id=episode_id) + '?token=' + encoded_id
        self.logger.debug(f'Fetching sources [{sources_link}]')
        resp = self._send_request(sources_link, return_type='json')
        sources = resp.get('result', {})
        self.logger.debug(f'Extracted sources: {sources}')

        # extract F2Cloud source id from available sources
        try:
            sources = { src['title']: src['id'] for src in sources }
            self.logger.debug(f'Extracted source ids: {sources}')
        except Exception as e:
            self.logger.warning(f'Failed to extract source ids with error: {e}')

        return sources

    # step-1
    def search(self, keyword, search_limit=5):
        '''
        search for movie/show based on a keyword using TMDB API.
        '''
        return self.search_client.search(keyword, search_limit)

    # step-2
    def fetch_episodes_list(self, target):
        '''
        fetch all available episodes list in the selected show
        '''
        all_episodes_list = []
        list_episodes_url = self.episodes_list_url.format(type=target['type'], tmdb_id=target['show_id'])

        self.logger.debug(f'Fetching soup to extract episodes from {list_episodes_url = }')
        soup = self._get_bsoup(list_episodes_url, silent=True)
        if soup is None:
            self.logger.error('Selected show not found in VidSrc catalog.')
            self._exit(1)

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

        return sorted(all_episodes_list, key=lambda x: (x.get('season'), x['episode']))     # sort by seasons (if exists) and episodes

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
                # There is a change in F2Cloud source id as on Jun-22, 2024.
                # Retained the previous source id for backward compatibility.
                provider_src_id = sources.get('F2Cloud')

                if provider_src_id:
                    encoded_id = self.provider_client._encode_data(self.ENCRYPTION_KEY, provider_src_id)
                    provider_src_url = self.provider_source_url.format(provider_id=provider_src_id) + '?token=' + encoded_id
                    link = self.provider_client._get_f2cloud_link(provider_src_url)
                else:
                    self.logger.warning('F2Cloud source id not found in sources')
                    link = None

                if link is not None:
                    # udb key format: s + SEASON + e + EPISODE / m + MOVIE
                    udb_item_key = f"s{episode.get('season')}e{episode.get('episode')}" if series_flag else f"m{episode.get('episode')}"
                    # add episode details & provider link to udb dict
                    self._update_udb_dict(udb_item_key, episode)
                    self._update_udb_dict(udb_item_key, {'providerLink': link, 'refererLink': link})

                    self.logger.debug(f'Extracting m3u8 links for {link = }')
                    # get download sources
                    m3u8_links = self.provider_client._resolve_sources(link)
                    if 'error' not in m3u8_links:
                        # get subtitles dictionary (key:value = language:link) and add to udb dict
                        subtitles = self.provider_client._get_provider_subtitles(link.split('?')[1])
                        self._update_udb_dict(udb_item_key, {'subtitles': subtitles})
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

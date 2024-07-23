__author__ = 'Prudhvi PLN'

import re

# modules for javascript execution
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from Clients.BaseClient import BaseClient
from Clients.IMDBClient import IMDBClient
from Clients.TMDBClient import TMDBClient
from Utils.commons import threaded


class SuperembedClient(BaseClient):
    '''
    Movies/Series Client using TheMovieDB/IMDB & Superembed APIs
    '''
    # step-0
    def __init__(self, config, session=None):
        preferred_search = config.get('preferred_search', '')
        # pad the configuration with required keys
        config.setdefault('Superembed', {})
        self.se_base_url = config['Superembed'].get('base_url', 'https://multiembed.mov/?tmdb=1&video_id={tmdb_id}')
        self.has_streambucket_url_element = config['Superembed'].get('has_streambucket_url_element', 'div.loading-text')
        self.stream_play_element = config['Superembed'].get('stream_play_element', 'div.play-button')
        self.stream_form_element = config['Superembed'].get('stream_form_element', '.form-button-click')
        self.stream_token_element = config['Superembed'].get('stream_token_element', 'input.input-button-click')
        self.source_list_element = config['Superembed'].get('source_list_element', 'ul.sources-list li')
        # Hard-coding these url paths for now. If there is an issue in future, make these dynamic by extracting them from main.js
        self.load_sources_link = config['Superembed'].get('load_sources_link', '/response.php')
        self.get_stream_source_link = config['Superembed'].get('get_stream_source_link', '/playvideo.php?video_id={video_id}&server_id={server_id}&token={load_sources_token}&init=0')

        # Config related to captcha
        self.captcha_message_element = config['Superembed'].get('captcha_message_element', '#captcha-message')
        self.captcha_element = config['Superembed'].get('captcha_element', 'div.captcha-holder')
        self.captcha_solver = config['Superembed'].get('captcha_solver', 'https://www.nyckel.com/v1/functions/5m8hktimwukzpb8r/invoke')
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

        self.logger.debug(f'Superembed client initialized with {config = }')
        self.driver = None
        self.button_token = {}      # placeholder for reusable token

    # step-2.1
    @threaded()
    def _get_episode_details(self, episode, season, streambucket_base_url, series_type):

        streambucket_url = streambucket_base_url.format(season=season, episode=episode)
        soup = self._get_bsoup(streambucket_url, silent=True)

        # Check if episode is present in Superembed catalog
        ep_name = soup.select(self.has_streambucket_url_element)[0].get_text(' - ', strip=True) if soup else None
        if ep_name is None or 'not found' in ep_name.lower():
            return {'error': 1, 'episode': episode}

        # Check if Streambucket ID is available
        streambucket_actual_url = self._regex_extract(r'btoa\("([^"]+)"\)', soup.select('script')[2].text, 1)
        if not streambucket_actual_url:
            return {'error': 2, 'episode': episode}

        episode_dict = {
            'type': series_type,
            'season': season,
            'episode': episode,
            'episodeName': self._windows_safe_string(ep_name),
            'streambucketLink': streambucket_actual_url
        }

        return episode_dict

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

    # step-4.1.1.1
    # TODO: Currently, this function retrieves the token using selenium to execute javascript code. Need to reverse engineer the javascript code.
    def _get_new_button_click_token(self, sb_url):
        '''
        Extract a new button-click token used to retrieve load_sources token
        '''
        self.logger.debug(f'Extracting button-click token from streambucket url: {sb_url}')

        # Creating webdriver instance, if does not exist, else reuse
        if self.driver:
            self.logger.debug('Reusing webdriver instance')
        else:
            self.logger.debug('Creating webdriver instance')
            self.driver = self._get_undetected_chrome_driver(client='Superembed')

        self.driver.get(sb_url)

        # Wait for the page to load and the button to be clickable
        wait = WebDriverWait(self.driver, self.request_timeout)
        button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, self.stream_play_element)))

        # This site creates a hidden token on click and submits immediately, so stop the form submission to retrieve the token.
        self.driver.execute_script("""
            var form = document.querySelector('%s');
            if (form) {
                form.onsubmit = function(event) {
                    event.preventDefault();
                    event.stopPropagation();
                    return false;
                };
            }
        """ % self.stream_form_element)

        # Click the button to trigger the token generation
        button.click()

        # Wait for the token to be generated and the hidden input field to be populated
        # Adjust the wait condition as per your page's behavior
        hidden_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, self.stream_token_element)))

        # Extract the token from the hidden input field
        button_token = hidden_input.get_attribute('value').strip()
        self.logger.debug(f"Extracted streambucket button-click token: {button_token}")

        return {'button-click': button_token}

    # step-4.1.1
    def _get_button_click_token(self, sb_url):
        '''
        Extract the button-click token used to retrieve load_sources token
        '''
        self.logger.debug('Extracting streambucket button-click token...')
        btn_token = self._load_udb_cookies(client='superembed')
        if btn_token:
            return btn_token

        # Load new cookies
        btn_token = self._get_new_button_click_token(sb_url)
        self._save_udb_cookies(client='superembed', data=btn_token)

        return btn_token

    # step-4.1
    def _get_load_sources_token(self, sb_url, retry=False):
        '''
        extract the token used to retrieve the available sources
        '''
        # Extract the load sources token using button-click token from above
        self.logger.debug(f'Extracting load sources token from streambucket url: {sb_url}')

        resp = self._send_request(sb_url, request_type='post', post_data=self.button_token)
        token = self._regex_extract(r'load_sources\("(.*)"\);', resp, 1)
        self.logger.debug(f'Extracted load sources token: {token}')

        if token: return token

        if retry:
            self.logger.warning(f'No load_sources token found!')
            return None
        elif self.driver is None:
            # Retry only if 1st attempt is done using reloaded cookies
            self.logger.debug('Retrying to extract load source token...')
            self.button_token = self._get_new_button_click_token(sb_url)
            # Save the newly loaded cookies
            self._save_udb_cookies(client='superembed', data=self.button_token)
            token = self._get_load_sources_token(sb_url, retry=True)
            return token

    # step-4.2.1
    def _solve_captcha(self, sb_pv_url, captcha_element, captcha_type, attempt=1):
        '''
        [BETA] Solve Gender-identification Captcha in Superembed. Works as of July 20, 2024.
        '''
        self.logger.debug(f'[Attempt: {attempt}] Solving captcha [type={captcha_type}]...')
        if captcha_type.lower() not in ('male', 'female'):
            self.logger.warning(f'Unknown captcha type: {captcha_type}')
            return

        # Extract captcha data
        captcha_base_url = '/'.join(sb_pv_url.split('/')[:3])
        captcha_id = captcha_element.select_one('input[type=hidden]').get('value')
        captcha_img_links = [ elem['src'] if elem['src'].startswith('https') else f"{captcha_base_url}/{elem['src']}" for elem in captcha_element.select('img') ]
        self.logger.debug(f'[Attempt: {attempt}] Extracted captcha elements: {captcha_id = }, {captcha_img_links = }')

        # Solve captcha. Works only if captcha is gender identification.
        captcha_answers = []
        for link in captcha_img_links:
            self.logger.debug(f'[Attempt: {attempt}] Finding gender of {link}')
            img_content = self._send_request(link, return_type='bytes', silent=True)
            img_data = self._send_request(self.captcha_solver, request_type='post', upload_data={'file': img_content})
            self.logger.debug(f'[Attempt: {attempt}] Gender data: {img_data}')
            img_id = link.split('/')[-1].split('.')[0]
            if 'woman' in img_data.lower():
                captcha_answers.append((img_id, 'female'))
            else:
                captcha_answers.append((img_id, 'male'))
        self.logger.debug(f'[Attempt: {attempt}] Captcha answers: {captcha_answers}')

        # Send solved captcha
        captcha_data = [ ('captcha_answer[]', answer) for answer, type in captcha_answers if type == captcha_type.lower() ]
        captcha_data.append(('captcha_id', captcha_id))
        self.logger.debug(f'[Attempt: {attempt}] Submitting captcha with data: {captcha_data}')
        soup = self._get_bsoup(sb_pv_url, request_type='post', post_data=captcha_data)

        # Validate if captcha is solved, else retry
        self.logger.debug(f'[Attempt: {attempt}] Checking if captcha is enabled...')
        captcha_element = soup.select_one(self.captcha_element)
        if captcha_element:
            self.logger.warning(f"[Attempt: {attempt}] Oops!!! It's Captcha Again!")
            if attempt > 1:
                self.logger.warning(f'Captcha is still enabled, even after {attempt} attempts')
                return
            captcha_type = soup.select_one(self.captcha_message_element).text.split()[-1]
            soup = self._solve_captcha(sb_pv_url, captcha_element, captcha_type, attempt+1)
        else:
            self.logger.info(f'[Attempt: {attempt}] Yay! Captcha is solved')

        return soup

    # step-4.2
    def _extract_stream_link(self, load_sources_token, source='vipstream'):
        '''
        extract stream source link for given source. Default is vipstream
        '''
        stream_link = None
        self.logger.debug(f'Extracting stream source link for source: {source}')

        # Extract the stream source components to construct the link
        load_sources_url = f'{self.episode_base_url}{self.load_sources_link}'
        soup = self._get_bsoup(load_sources_url, request_type='post', post_data={'token': load_sources_token}, extra_headers={'x-requested-with': 'XMLHttpRequest'})
        selected_source = [ i for i in soup.select(self.source_list_element) if i.select(f'.server-{source}') ] if soup else []
        if len(selected_source) == 0:
            return {'error': f'Stream source [{source}] not found'}
        video_id = selected_source[0].get('data-id')
        server_id = selected_source[0].get('data-server')
        self.logger.debug(f'Extracted details for stream source [{source}]: {video_id = }, {server_id = }')

        # Construct the link to fetch stream source link
        sb_playvideo_url = self.episode_base_url + self.get_stream_source_link.format(video_id=video_id, server_id=server_id, load_sources_token=load_sources_token)

        try:
            self.logger.debug(f'Extracting stream source using: {sb_playvideo_url}')
            soup = self._get_bsoup(sb_playvideo_url)

            # Check if captcha is enabled and solve it
            self.logger.debug('Checking if captcha is enabled...')
            captcha_element = soup.select_one(self.captcha_element)
            if captcha_element:
                self.logger.warning("Oops!!! It's Captcha")
                captcha_type = soup.select_one(self.captcha_message_element).text.split()[-1]
                soup = self._solve_captcha(sb_playvideo_url, captcha_element, captcha_type)
            else:
                self.logger.debug('Alright! Captcha is not enabled')

            self.logger.debug('Extracting stream source link')
            stream_link = soup.select_one('iframe').get('src')
            self.logger.debug(f'Extracted stream source link for source [{source}]: {stream_link}')
            return stream_link

        except Exception as e:
            self.logger.warning(f'Failed to fetch stream source link with error: {e}')
            return {'error': f'Stream link not found for source: {source}'}

    # step-4.3.1
    def _decode_hunter(self, h, u, n, t, e, r):
        '''
        python implementation of javascript's hunter function
        '''
        def _hunter_inner(d, e, f):
            charset = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/"
            source_base = charset[:e]
            target_base = charset[:f]
            result = 0

            # Calculate the decimal value of the input string
            for power, digit in enumerate(d[::-1]):
                if digit in source_base:
                    result += source_base.index(digit) * e**power

            converted_result = ""
            while result > 0:
                converted_result = target_base[result % f] + converted_result
                result = (result - (result % f)) // f

            return converted_result or "0"

        result = ""
        i = 0

        while i < len(h):
            s = ""
            while h[i] != n[e]:
                s += h[i]
                i += 1
            for j in range(len(n)):
                s = s.replace(n[j], str(j))
            result += chr(int(_hunter_inner(s, e, 10)) - t)
            i += 1

        return result

    # step-4.3
    def _resolve_vipstream_source(self, stream_link):
        '''
        extract m3u8 link & subtitles dict from vipstream source link
        '''
        # Get hunter arguments
        self.logger.debug(f'Extracting hunter arguments from vipstream source link: {stream_link}')
        response = self._send_request(stream_link)
        try:
            h, u, n, t, e, r = eval(self._regex_extract(r'\("(.*?),(.*?),(.*?),(.*?),(.*?),(.*?)\)', response, 0))
            self.logger.debug(f'Extracted hunter arguments: {h}, {u}, {n}, {t}, {e}, {r}')
        except Exception as e:
            self.logger.warning(f'Failed to extract hunter arguments with error: {e}')
            return {'error': 'Failed to extract decoding data'}

        # Decode the m3u8 data using hunter function
        self.logger.debug('Decoding data using hunter...')
        decoded_data = self._decode_hunter(h, u, n, t, e, r)
        self.logger.debug(f'Decoded data from hunter: {decoded_data}')

        # Extract the m3u8 & subtitle links from decoded data
        self.logger.debug(f'Extracting m3u8 & subtitle links from decoded data')
        m3u8_links, subtitles = [], {}
        links = [ i.group(1) for i in re.finditer('file:"([^"]+)"', decoded_data) ]
        m3u8_links = [ {'file': link} for link in links ]
        subs = [ i.group(1) for i in re.finditer('subtitle:"([^"]+)"', decoded_data) ]
        for _subs in subs:
            for sub in _subs.split(','):
                lang, url = sub.rsplit(']', 1)
                subtitles[lang.strip('[')] = url
        self.logger.debug(f'Extracted m3u8 & subtitle links: {m3u8_links = }, {subtitles = }')

        return m3u8_links, subtitles

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
        # This function will only check if series / movie is available if superembed
        all_episodes_list = []
        # Remove tmdb flag, if the id is from IMDB
        if target['show_id'].startswith('tt'):
            self.se_base_url = self.se_base_url.replace('tmdb=1&', '')
        streambucket_base_url = self.se_base_url.format(tmdb_id=target['show_id'])

        if target['type'] == 'tv':
            streambucket_base_url = streambucket_base_url + '&s={season}&e={episode}'
            # filter out special seasons
            seasons_to_fetch = { int(season.split()[-1]):int(episodes) for season, episodes in target['episodes_per_season'].items() if season.split()[-1].isdigit() }
            # set message formats for logging
            debug_msg = 'Fetching superembed episode urls for season: {season}'
            not_found_err_msg = 'Season {season} Episode {episode} not found in Superembed catalog.'
            no_id_err_msg = 'Streambucket URL not found for: Season {season} Episode {episode}.'
        else:
            # set season & epsiode to 1 for movie
            seasons_to_fetch = {1:1}
            debug_msg = 'Fetching superembed movie url'
            not_found_err_msg = 'Movie not found in Superembed catalog'
            no_id_err_msg = 'Streambucket URL not found for selected movie.'

        for season, episodes in seasons_to_fetch.items():
            self.logger.debug(debug_msg.format(season=season))
            # multi-threaded fetch of streambucket url for each episode
            items = [ episode for episode in range(1, episodes+1) ]
            episode_dicts = self._get_episode_details(items, season, streambucket_base_url, target['type'])
            for episode_dict in episode_dicts:
                if episode_dict.get('error', 0) == 1:
                    self.logger.error(not_found_err_msg.format(season=season, episode=episode_dict['episode']))
                elif episode_dict.get('error', 0) == 2:
                    self.logger.error(no_id_err_msg.format(season=season, episode=episode_dict['episode']))
                else:
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

                self.episode_base_url = '/'.join(episode.get('streambucketLink').split('/')[:3])
                # One-time load button-click token
                if not self.button_token: self.button_token = self._get_button_click_token(episode.get('streambucketLink'))
                load_sources_token = self._get_load_sources_token(episode.get('streambucketLink'))

                if load_sources_token is not None:
                    # update udb dict with error details (if any) and move to next episode
                    link = self._extract_stream_link(load_sources_token, source='vipstream')
                    if 'error' in link:
                        self._show_episode_links(episode.get('episode'), link, display_prefix)
                        continue

                    # udb key format: s + SEASON + e + EPISODE / m + MOVIE
                    udb_item_key = f"s{episode.get('season')}e{episode.get('episode')}" if series_flag else f"m{episode.get('episode')}"
                    # add episode details & vidplay link to udb dict
                    self._update_udb_dict(udb_item_key, episode)
                    self._update_udb_dict(udb_item_key, {'streamLink': link, 'refererLink': link})

                    self.logger.debug(f'Extracting m3u8 links for {link = }')
                    # get download sources & subtitles dictionary (key:value = language:link) and add to udb dict
                    m3u8_links, subtitles = self._resolve_vipstream_source(link)
                    if subtitles: self._update_udb_dict(udb_item_key, {'subtitles': subtitles})
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

    # step-7
    def cleanup(self):
        '''
        Perform any clean-up activities as required.
        '''
        # Close driver at the end, so that we can reuse.
        if self.driver:
            self.logger.debug('Closing the webdriver instance')
            self.driver.close()
            self.driver.quit()

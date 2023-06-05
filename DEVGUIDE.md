# UDB [Ultimate-Download-Bot]
`
Anime/Drama series downloader. Downloads the file using Http Live Streaming (HLS) as m3u8 and converts to mp4 using ffmpeg
`

## Developer Guide (for the future me)
### HLS
 - HLS means Http Live Streaming. In IDM, you can see the file ending as .ts
 - It will contain main file .m3u8 which contains details of the segment files and a key
 - Algorithm to download this file:
   - download all segments in .m3u8 & decrypt if required
   - combine the segments in same order as in m3u8
   - convert the combined file to mp4 using ffmpeg
 - Coding this algo is fun, but you are lazy, so you are using m3u8downloader pip package

### Process Flow
 - get search results from __search_url__ _(every anime has a uid)_
 - for anime selected from above, get the episodes list from __episodes_list_url__ _(every episode has a uid)_
 - for episodes selected from above, get the download links _(kwik links)_ from __download_link_url__ _(every Kwik download link has a uid)_
 - from above kwik links, get the m3u8 stream link _(requires __episode_url__ as referer)_
 - from above m3u8 links, download the stream data and convert to mp4 _(requires __kwik link__ as referer)_
 - Download Logic:
   - get content of m3u8 file and download all links (segments & keys) to a local temp dir
   - rewrite http links in m3u8 file with local temp paths and download it to temp dir
   - use ffmpeg to merge and convert the segments into mp4
   - _Note: ffmpeg can be used to download & convert to mp4 directly but it is sooo slow. So we download segments using threadpool and then convert it to mp4_
   - We can also convert it without ffmpeg but it is an extra pain

### Function Flow
```
 > Initialize AnimeClient as AC > AC.search > AC.show_search_results (pretty print)

 > AC.fetch_episodes_list (get list of episodes) > AC.show_episode_results (pretty print episodes)

 > get episodes required from user > AC.fetch_episode_links (get kwik links for required episodes in jpn lang) > AC.show_episode_links (pretty print)

 > get required resolution from user > fetch_m3u8_links > AC.get_m3u8_content > parse_m3u8_link (extract m3u8 url by decoding javascript)

 > batch_downloader (start download using ThreadPool) > m3u8_downloader > Initialize HLSDownloader as HLS > HLS.downloader()
 ```
 - AnimeClient is specific to a website
 - DramaClient is 70% generic. Just modify the config per website
 - HLSDownloader is 90% universal. 10% depends on HLS. If a new technique comes up in HLS, this needs to be updated

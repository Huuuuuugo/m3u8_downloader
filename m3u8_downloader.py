import hashlib
import shutil
import json
import time
import os
import re

import ffmpeg

from downloader import Download

class PartInfo():
    def __init__(self, downloaded: bool = False, url: str = None, duration: float = None, range: str = None, index: str = None):
        self.downloaded = downloaded
        self.url = url
        self.duration = duration
        self.range = range
        self.index = index
    
    def __repr__(self):
        return f'url: {self.url}, duration: {self.duration}, range: {self.range}, index: {self.index}'
    
    # saves a json file of a serializable that contains a PartInfo object
    @classmethod
    def save_json(cls, obj, path):
        def new_default(obj):
            if isinstance(obj, PartInfo):
                return obj.__dict__

            else:
                return obj
            
        with open(path, 'w', encoding='utf8') as json_file:
            json_file.write(json.dumps(obj, indent=2, default=new_default))
    
    # loads as json file that contains instances of PartInfo
    @classmethod
    def load_json(cls, path):
        def new_object_hook(obj):
            if isinstance(obj, dict):
                part_info_dict = PartInfo().__dict__
                for key in obj.keys():
                    if key not in part_info_dict.keys():
                        return obj
                
                return PartInfo(**obj)

            else:
                return obj
            
        with open(path, 'r', encoding='utf8') as json_file:
            return json.loads(json_file.read(), object_hook=new_object_hook)
    
    
class M3U8Downloader():
    def __init__(
            self, 
            m3u8_path: str, 
            output_file: str, 
            headers: dict |  None = None, 
            label: str = '',
            temp_dir: str = '', 
            max_downloads: int = 5, 
            max_retries: int = 5
        ):

        # general attributes
        self.m3u8_path = m3u8_path
        self.output_file = os.path.abspath(output_file)
        self.file_extension = os.path.basename(output_file).rsplit('.')[-1]
        self.download_dir = './temp_m3u8_downloader/'
        self.headers = headers
        if headers is None: 
            self.headers = {}
            
        self.max_retries = max_retries
        self.max_downloads = max_downloads

        # creates a temporary directory based on the path of the output file
        if temp_dir == '':
            output_hash = hashlib.sha256(self.output_file.encode())
            output_hash = output_hash.hexdigest()
            self.temp_dir = f'{self.download_dir}{output_hash}/'

        os.makedirs(self.temp_dir, exist_ok=True)
        
        # creates directory for parts
        self.parts_dir = f'{self.temp_dir}parts/'
        os.makedirs(self.parts_dir, exist_ok=True)

        # path to the local m3u8 file
        self.local_m3u8_path = f'{self.temp_dir}local.m3u8'

        # assigns a name to be displayed along with download progress
        if label == '':
            self.label = os.path.basename(output_file)
        
        # get info from the m3u8, if this file has already been read before, reuse the previous version
        # to keep track of what has already been downloaded
        self.parts_json_path = f'{self.temp_dir}parts.json'
        if os.path.exists(self.parts_json_path):
            self.parts = PartInfo.load_json(self.parts_json_path)
        
        else:
            self.parts = self._extract_info()
            PartInfo.save_json(self.parts, self.parts_json_path)
            
        # attributes used for tracking progress   
        self.total_parts = len(self.parts) - 1
        self.curr_part = 0

    
    @property
    def progress(self):
        return (self.curr_part / self.total_parts) * 100
    
    # TODO: create method to update links
    # sometimes the m3u8 file for the same video can contain different parameters on the urls of its parts
    # depending on when it was generated, to allow downloads to continue even after a new m3u8 is
    # genereated for the same video file, it's necessary to update the links on the json file
    # without changing the other information.
    # probably just need to rerun _extract_info() and update the links one by one using a for enumerate loop
    # between the old and new json
    def _extract_info(self) -> list[PartInfo]:
        with open(self.m3u8_path) as playlist:
            lines = playlist.readlines()

            part = PartInfo()
            parts_info: list[dict] = []
            part_index = 1

            # iterate through all lines extracting info about each part
            for line in lines:
                # if time was not yet assigned for that part, keep looking for it
                if part.duration is None:
                    matches = re.findall(r"#EXTINF:(.+),", line)
                    if matches:
                        part.duration = float(matches[0])
                
                # if time was already assigned, get search for the rest of the infomarion about that part
                else:
                    # check for range information
                    byterange_match = re.findall(r"#EXT-X-BYTERANGE:.*?(\d+)@(\d+)", line)
                    if byterange_match:
                        end, start = map(int, byterange_match[0])
                        end = start + end - 1
                        range_str = f'{start}-{end}'

                        part.range = range_str
                        
                    # if the line contains an url, add it to the part_dict and prepare to get the next part
                    url_match = re.match(r"https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)", line)
                    if url_match:
                        # save part url
                        part.url = url_match[0]

                        # assign a index representing its position on the m3u8 file
                        part.index = str(part_index).zfill(4)

                        # add to the list of parts and reset the part_dict
                        parts_info.append(part)
                        part = PartInfo()
                        part_index += 1
                    
                    # TODO: add support for skip and key tags

        return parts_info

    # TODO: deal with unsatisfiable ranges
    # TODO: make it threaded
    # TODO: remove dependency on downloader.py
    def _download_parts(self):
        try:
            active_downloads = []
            for part in self.parts:
                print(self.progress)
                self.curr_part += 1
                if part.downloaded:
                    continue

                # start download and append to list of downloads
                try:
                    headers = self.headers.copy()
                    if part.range is not None:
                        headers.update({'Range': part.range})

                    part_path = f'{self.parts_dir}{part.index}.{self.file_extension}'
                    download_obj = Download(part.url, part_path, headers=headers, max_retries=self.max_retries, try_continue=False)
                    download_obj.start()
                    active_downloads.append({'part': part, 'download': download_obj})

                except ValueError:
                    continue
                
                # wait if the limit of simultaneous downloads has been reached or all the file has been read
                while ((len(active_downloads) >= self.max_downloads) 
                or (self.total_parts - self.curr_part <= self.max_downloads)):
                    # check for download progress
                    finished_indexes = []
                    for i, download_dict in enumerate(active_downloads):
                        if not download_dict['download'].is_running:
                            # update list of finished downloads
                            download_dict['part'].downloaded = True
                            PartInfo.save_json(self.parts, self.parts_json_path)

                            # set it to be deleted from active downloads
                            finished_indexes.append(i)
                        
                    # update list of active downloads
                    offset = 0
                    for index in finished_indexes:
                        active_downloads.pop(index-offset)
                        offset += 1
                    
                    if len(active_downloads) == 0:
                        break
                    
                    time.sleep(0.01)
        
        finally:
            PartInfo.save_json(self.parts, self.parts_json_path)
    

    def _create_local_m3u8(self):
        with open(self.local_m3u8_path, 'w', encoding='utf8') as local_m3u8:
            local_m3u8.write('#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-MEDIA-SEQUENCE:1\n')

            for part in self.parts:
                part_path = os.path.abspath(f'{self.parts_dir}{part.index}.{self.file_extension}')
                local_m3u8.write(f'#EXTINF:{part.duration},\n')
                local_m3u8.write(f'{part_path}\n')
            
            local_m3u8.write('#EXT-X-ENDLIST')
    

    def _concat(self):
        ffmpeg.input(self.local_m3u8_path).output(self.output_file, c='copy', y=None).run()
    

    def download(self):
        # download parts and generate output file
        self._download_parts()
        self._create_local_m3u8()
        self._concat()

        # delete the temp_dir
        shutil.rmtree(self.temp_dir)

        # attempts to delete the temp_download_dir
        try:
            os.rmdir(self.download_dir)
        except OSError:
            pass

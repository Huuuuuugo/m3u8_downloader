import hashlib
import os
import re

class PartInfo():
    def __init__(self):
        self.url = None
        self.duration = None
        self.range = None
        self.index = None
    
    def __repr__(self):
        return f'url: {self.url}, duration: {self.duration}, range: {self.range}, index: {self.index}'

# TODO: progress property
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
        self.download_dir = './temp_m3u8_downloader/'

        # necessary args
        self.m3u8_path = m3u8_path
        self.output_file = os.path.abspath(output_file)
        self.file_extension = os.path.basename(output_file).rsplit('.')[-1]

        # optional args
        if headers is None:
            self.headers = {}

        if label == '':
            self.label = os.path.basename(output_file)

        if temp_dir == '':
            output_hash = hashlib.sha256(self.output_file.encode())
            output_hash = output_hash.hexdigest()
            self.temp_dir = f'{self.download_dir}{output_hash}/'

        # other attributes
        self.parts = self._extract_info()
        self.total_parts = len(self.parts) - 1
        self.curr_part = 0
    
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



import argparse
import requests
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO
from urllib.parse import urljoin

def fetch_high_res_icons(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    icons = []
    for link in soup.find_all('link', rel=lambda value: value and 'icon' in value.lower()):
        if link.get('href'):
            icon_url = link['href']
            if icon_url.startswith('/'):
                icon_url = urljoin(url, icon_url)
            icons.append(icon_url)
    return icons

def download_image(image_url):
    response = requests.get(image_url)
    image = Image.open(BytesIO(response.content))
    return image

def find_best_icon(icons, size_threshold=150):
    best_icon = None
    max_size = 0
    for icon_url in icons:
        try:
            image = download_image(icon_url)
            width, height = image.size
            if width >= size_threshold and height >= size_threshold:
                if width < height:
                    min_dimension = width
                else:
                    min_dimension = height
                if not best_icon or min_dimension < max_size:
                    best_icon = icon_url
                    max_size = min_dimension
            elif width * height > max_size:
                best_icon = icon_url
                max_size = width * height
        except Exception as e:
            print(f"Failed to process icon {icon_url}: {e}")
    return best_icon

def main(urls):
    for url in urls:
        icons = fetch_high_res_icons(url)
        best_icon = find_best_icon(icons)
        print(f"The best icon for {url} is: {best_icon}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch and determine the best high-resolution icon for given URLs.")
    parser.add_argument('urls', nargs='+', help='One or more URLs to fetch icons from.')
    args = parser.parse_args()
    
    if args.urls:
        main(args.urls)
    else:
        parser.print_help()

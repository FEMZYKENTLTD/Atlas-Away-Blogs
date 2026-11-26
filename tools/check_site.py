#!/usr/bin/env python3
"""Check the two HTML documents and their local links using only Python's standard library."""
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

SITE = Path(__file__).resolve().parents[1]
VOID = set('area base br col embed hr img input link meta param source track wbr'.split())


@dataclass
class Element:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.walk()

    def text(self):
        return ' '.join(''.join(
            child if isinstance(child, str) else child.text() for child in self.children
        ).split())

    def direct(self, tag):
        return [child for child in self.children if isinstance(child, Element) and child.tag == tag]

    def has_class(self, name):
        return name in self.attrs.get('class', '').split()


class Document(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.root = Element('#document')
        self.stack = [self.root]
        self.feed(path.read_text(encoding='utf-8'))
        self.close()

    def handle_starttag(self, tag, attrs):
        element = Element(tag, dict(attrs))
        self.stack[-1].children.append(element)
        if tag not in VOID:
            self.stack.append(element)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, value):
        self.stack[-1].children.append(value)


def require(condition, message):
    if not condition:
        raise SystemExit(f'FAIL: {message}')


REGIONS = {
    'europe': {'France': ['Paris', 'Nice', 'Marseille'], 'Italy': ['Rome', 'Florence', 'Venice'],
               'Greece': ['Athens', 'Thessaloniki', 'Santorini']},
    'asia': {'Japan': ['Tokyo', 'Kyoto', 'Osaka'], 'China': ['Beijing', 'Shanghai', "Xi'an"],
             'India': ['New Delhi', 'Mumbai', 'Jaipur']},
    'america': {'USA': ['New York City', 'Los Angeles', 'Chicago'],
                'Brazil': ['Rio de Janeiro', 'São Paulo', 'Salvador'],
                'Canada': ['Toronto', 'Vancouver', 'Montreal']},
    'africa': {'South Africa': ['Cape Town', 'Johannesburg', 'Durban'],
               'Egypt': ['Cairo', 'Luxor', 'Sharm El Sheikh'],
               'Morocco': ['Marrakech', 'Casablanca', 'Fez']},
}
LANDMARKS = [('Paris', 'eiffel-tower'), ('Rome', 'colosseum'), ('New York', 'statue-of-liberty')]


def main():
    paths = sorted(SITE.glob('*.html'))
    require([path.name for path in paths] == ['index.html', 'travel-stories.html'],
            'The project must have exactly its two expected HTML pages.')
    docs = {path: list(Document(path).root.walk()) for path in paths}
    ids = {path: {node.attrs['id']: node for node in nodes if 'id' in node.attrs}
           for path, nodes in docs.items()}
    checked_links = 0
    for path, nodes in docs.items():
        counts = Counter(node.attrs['id'] for node in nodes if 'id' in node.attrs)
        require(all(value == 1 for value in counts.values()), f'Duplicate IDs in {path.name}.')
        require(sum(node.tag == 'h1' for node in nodes) == 1, f'Expected one h1 in {path.name}.')
        require(sum(node.tag == 'style' for node in nodes) == 1, f'Expected embedded CSS in {path.name}.')
        require(not any(node.tag == 'script' for node in nodes), f'Unexpected script in {path.name}.')
        for node in nodes:
            links = [node.attrs[attr] for attr in ('href', 'src') if node.attrs.get(attr)]
            links += [entry.split()[0] for entry in node.attrs.get('srcset', '').split(',') if entry.strip()]
            for address in links:
                url = urlsplit(address)
                if url.scheme or url.netloc:
                    continue
                target = (path.parent / unquote(url.path)).resolve() if url.path else path
                require(target.is_relative_to(SITE) and target.is_file(), f'Broken asset or page: {address}.')
                if url.fragment:
                    require(unquote(url.fragment) in ids.get(target, {}), f'Broken fragment: {address}.')
                checked_links += 1

    home = SITE / 'index.html'
    blocks = [node for node in docs[home] if node.tag == 'a' and node.has_class('region-block')]
    require(len(blocks) == 4, 'The home page needs four numbered links.')
    for index, (block, (region, countries)) in enumerate(zip(blocks, REGIONS.items()), 1):
        number = [node.text() for node in block.walk() if node.has_class('block-number')]
        require(number == [str(index)] and block.attrs.get('href') == f'#{region}',
                f'Block {index} should point to #{region}.')
        panel = ids[home].get(region)
        ordered = panel.direct('ol') if panel else []
        require(len(ordered) == 1 and len(ordered[0].direct('li')) == 3,
                f'Expected one three-item country list in #{region}.')
        for item, (country, places) in zip(ordered[0].direct('li'), countries.items()):
            require([heading.text() for heading in item.direct('h4')] == [country],
                    f'Country order is incorrect for #{region}.')
            unordered = item.direct('ul')
            require(len(unordered) == 1 and [li.text() for li in unordered[0].direct('li')] == places,
                    f'Nested places for {country} do not match the assignment.')

    stories = SITE / 'travel-stories.html'
    tables = [node for node in docs[stories] if node.tag == 'table']
    require(len(tables) == 1 and len(tables[0].direct('tbody')) == 1, 'Expected one landmark table.')
    rows = tables[0].direct('tbody')[0].direct('tr')
    require(len(rows) == 3, 'Expected three landmark rows.')
    for row, (city, fragment) in zip(rows, LANDMARKS):
        headers, cells = row.direct('th'), row.direct('td')
        require(len(headers) == len(cells) == 1 and headers[0].attrs.get('scope') == 'row',
                f'{city} must have a row header and an attraction cell.')
        require(any(node.has_class('place-name') and node.text() == city for node in headers[0].walk()),
                f'Expected the {city} row.')
        anchor = cells[0].direct('a')
        require(len(anchor) == 1 and anchor[0].attrs.get('href') == f'#{fragment}', f'Wrong link for {city}.')
        images = [node for node in anchor[0].walk() if node.tag == 'img' and node.attrs.get('alt')]
        require(len(images) == 1, f'The {city} photo must be linked and have alt text.')
        require(ids[stories][fragment].tag == 'article', f'Expected a field note for {city}.')

    print(f'PASS: 2 HTML pages, {checked_links} local link/asset references, unique IDs.')
    print('PASS: 4 numbered links, 12 ordered countries, 36 correctly nested places.')
    print('PASS: 3 linked photos with descriptive alternatives and matching field notes.')


if __name__ == '__main__':
    main()

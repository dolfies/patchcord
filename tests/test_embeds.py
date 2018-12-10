"""

Litecord
Copyright (C) 2018  Luna Mendes

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""

from litecord.schemas import validate
from litecord.embed.schemas import EMBED_OBJECT

def validate_embed(embed):
    return validate(embed, EMBED_OBJECT)

def valid(embed: dict):
    try:
        validate_embed(embed)
        return True
    except:
        return False

def invalid(embed):
    try:
        validate_embed(embed)
        return False
    except:
        return True


def test_empty_embed():
    valid({})


def test_basic_embed():
    assert valid({
        'title': 'test',
        'description': 'acab',
        'url': 'https://www.w3.org',
        'color': 123
    })


def test_footer_embed():
    assert invalid({
        'footer': {}
    })

    assert valid({
        'title': 'test',
        'footer': {
            'text': 'abcdef'
        }
    })

def test_image():
    assert invalid({
        'image': {}
    })

    assert valid({
        'image': {
            'url': 'https://www.w3.org'
        }
    })

def test_author():
    assert invalid({
        'author': {
            'name': ''
        }
    })

    assert valid({
        'author': {
            'name': 'abcdef'
        }
    })

def test_fields():
    assert valid({
        'fields': [
            {'name': 'a', 'value': 'b'},
            {'name': 'c', 'value': 'd', 'inline': False},
        ]
    })

    valid({
        'fields': [
            {'name': 'a'},
        ]
    })
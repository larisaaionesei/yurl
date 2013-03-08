import re
from collections import namedtuple

from .utils import remove_dot_segments

# This module based on rfc3986.


# Validation errors.

class InvalidScheme(ValueError): pass
class InvalidAuthority(ValueError): pass
class InvalidUserinfo(InvalidAuthority): pass
class InvalidHost(InvalidAuthority): pass
class InvalidPath(ValueError): pass
class InvalidQuery(ValueError): pass


URLTuple = namedtuple('URLBase', 'scheme userinfo host port '
                                 'path query fragment')  # 4, 5, 6


class URL(URLTuple):
    """
    Class for manipulation with escaped parts of url.
    It can parse any url from string or can be constructed with provided parts.
    If source of url not trusted, method validate() can be used to check url.
    """
    __slots__ = ()

    # This is not validating regexp.
    # It splits url to unambiguous parts according RFC.
    _split_re = re.compile(r'''
        (?:([^:/?#]+):)?            # scheme
        (?://                       # authority
            (?:([^/?\#@]*)@)?       # userinfo
            ([^/?\#]*)()            # host:port
        )?
        ([^?\#]*)                   # path
        \??([^\#]*)                 # query
        \#?(.*)                     # fragment
        ''', re.VERBOSE | re.DOTALL).match

    def __new__(cls, url=None, scheme='', userinfo='', host='', port='',
                path='', query='', fragment=''):
        if url is not None:
            # All other arguments are ignored.
            (scheme, userinfo, host, port,
             path, query, fragment) = cls._split_re(url).groups('')

            # Host itself can contain digits and ':', so we cant use regexp.
            # It is bit different from other behaviors: instead of splitting
            # as is, and raise on validate, we split port only with digits.
            # I believe this is expected behavior.
            _port_idx = host.rfind(':')
            if _port_idx >= 0:
                _port = host[_port_idx + 1:]
                if not _port or _port.isdigit():
                    host, port = host[:_port_idx], _port

        else:
            # | If a URI contains an authority component, then the path
            # | component must either be empty or begin with a slash ("/")
            # | character.
            if userinfo or host or port:
                if path and path[0] != '/':
                    path = '/' + path

        # | Although schemes are case-insensitive, the canonical form
        # | is lowercase. An implementation should only produce lowercase
        # | scheme names for consistency.

        # | Although host is case-insensitive, producers and normalizers
        # | should use lowercase for registered names and hexadecimal
        # | addresses for the sake of uniformity.

        return tuple.__new__(cls, (scheme.lower(), userinfo, host.lower(),
                                   str(port), path, query, fragment))

    ### Serialization

    def __unicode__(self):
        scheme = self[0]
        path = self[4]
        base = self.authority

        # Escape path with slashes by adding explicit empty host.
        if base or path[0:2] == '//':
            base = '//' + base

        elif not scheme and path:
            # if url starts with path with ':'' in first segment
            column_idx = path.find(':')
            if column_idx > 0 and path.find('/', 0, column_idx) < 0:
                base = './'

        if scheme:
            base = scheme + ':' + base

        return base + self.full_path

    as_string = __unicode__

    def __reduce__(self):
        return type(self), (None,) + tuple(self)

    ### Missing properties

    # | The userinfo subcomponent may consist of a user name and, optionally,
    # | scheme-specific information about how to gain authorization to access
    # | the resource.
    @property
    def username(self):
        return self[1].partition(':')[0]

    @property
    def authorization(self):
        return self[1].partition(':')[2]

    @property
    def authority(self):
        userinfo, base, port = self[1:4]

        if port:
            base += ':' + port

        elif ':' in base:
            if base[base.rfind(':') + 1:].isdigit():
                base += ':'

        if userinfo:
            base = userinfo + '@' + base

        return base

    @property
    def full_path(self):
        path, query, fragment = self[4:7]

        if query:
            path += '?' + query

        if fragment:
            path += '#' + fragment

        return path

    ### Information

    def __nonzero__(self):
        return any(self)

    def has_authority(self):
        # micro optimization: self[2] hits more often then others
        return bool(self[2] or self[1] or self[3])

    def is_relative(self):
        # In terms of rfc relative url have no scheme.
        # See is_relative_path().
        return not self[0]

    def is_relative_path(self):
        # Relative-path url will not replace path during joining.
        return not self[0] and (self[4][0] != '/'
                                if self[4]
                                else not self.has_authority())

    def is_host_ipv4(self):
        if self[2][:1] != '[':
            parts = self[2].split('.')
            if len(parts) == 4 and all(part.isdigit() for part in parts):
                if all(int(part, 10) < 256 for part in parts):
                    return True
        return False

    def is_host_ip(self):
        if self.is_host_ipv4():
            return True

        if self[2][:1] == '[' and self[2][-1:] == ']':
            return True

        return False

    ### Validation

    _valid_scheme_re = re.compile(r'^[a-z][a-z0-9+\-.]*$').match
    # '[' and ']' the only chars not allowed in userinfo and not delimiters
    _valid_userinfo_re = re.compile(r'^[^/?\#@\[\]]+$').match
    _valid_reg_name_re = re.compile(r'^[^/?\#@\[\]:]+$').match
    _valid_path_re = re.compile(r'^[^?\#]+$').match
    _valid_query_re = re.compile(r'^[^\#]+$').match
    # This primitive regular expression not match complicated ip literal.
    _valid_ip_literal_re = re.compile(r'''
        ^(?:
            v[a-f0-9]+\.[a-z0-9\-._~!$&'()*,;=:]+
            |
            [a-f0-9:\.]+
        )$
        ''', re.VERBOSE | re.IGNORECASE).match

    def validate(self):
        if self[0]:
            if not self._valid_scheme_re(self[0]):
                raise InvalidScheme()

        if self[1]:
            if not self._valid_userinfo_re(self[1]):
                raise InvalidUserinfo()

        host = self[2]
        if host:
            if host[:1] == '[' and host[-1:] == ']':
                if not self._valid_ip_literal_re(host[1:-1]):
                    raise InvalidHost()

            # valid ipv4 is also valid reg_name
            elif not self._valid_reg_name_re(host):
                raise InvalidHost()

        # Acording rfc there is two cases when path can be invalid:
        # There should be no scheme and authority and first segment of path
        # should contain ':' or starts with '//'. But this library not about
        # punish user. We can escape this paths when formatting string.
        if self[4]:
            if not self._valid_path_re(self[4]):
                raise InvalidPath()

        if self[5]:
            if not self._valid_query_re(self[5]):
                raise InvalidQuery()

        return self

    ### Manipulation

    def __add__(self, other):
        # This method designed with one issue. By rfc delimeters without
        # following values are matter. For example:
        # 'http://ya.ru/page' + '//?none' = 'http:?none'
        # 'http://ya.ru/page?param' + '?' = 'http://ya.ru/page'
        # But the parser makes no distinction between empty and undefined part.
        # 'http://ya.ru/page' + '//?none' = 'http://ya.ru/page?none'
        # 'http://ya.ru/page?param' + '?' = 'http://ya.ru/page?param'
        # Same bug also present in urllib.parse.urljoin.
        # I hope it will be fixed in future yurls.

        if not isinstance(other, URLTuple):
            raise NotImplementedError()

        scheme, userinfo, host, port, path, query, fragment = other

        if not scheme:
            scheme = self[0]

            if not (host or userinfo or port):
                userinfo, host, port = self[1:4]

                if not path:
                    path = self[4]

                    if not query:
                        query = self[5]

                else:
                    if path[0] != '/':
                        parts = self[4].rpartition('/')
                        path = parts[0] + parts[1] + path

        return URL.__new__(type(self), None, scheme, userinfo, host, port,
                           remove_dot_segments(path), query, fragment)

    def __radd__(self, left):
        # if other is instance of URL(), __radd__() should not be called.
        if type(left) == URLTuple:
            return URL.__add__(left, self)

        raise NotImplementedError()

    def replace(self, scheme=None, userinfo=None, host=None, port=None,
                path=None, query=None, fragment=None,
                authority=None, full_path=None):
        if authority is not None:
            if host or userinfo or port:
                raise TypeError()

            # Use original URL just for parse.
            userinfo, host, port = URL('//' + authority)[1:4]

        if full_path is not None:
            if path or query or fragment:
                raise TypeError()

            # Use original URL just for parse.
            path, query, fragment = URL(full_path)[4:7]

        return URL.__new__(type(self), None,
                           self[0] if scheme is None else scheme,
                           self[1] if userinfo is None else userinfo,
                           self[2] if host is None else host,
                           self[3] if port is None else port,
                           self[4] if path is None else path,
                           self[5] if query is None else query,
                           self[6] if fragment is None else fragment)

    def setdefault(self, scheme='', userinfo='', host='', port='', path='',
                   query='', fragment=''):
        return URL.__new__(type(self), None,
                           self[0] or scheme,
                           self[1] or userinfo,
                           self[2] or host,
                           self[3] or port,
                           self[4] or path,
                           self[5] or query,
                           self[6] or fragment)

    ### Python 2 to 3 compatibility

    import sys
    if sys.version_info > (3, 0):
        # Rename __unicode__ function to __str__ in python 3.
        __str__ = __unicode__
        del __unicode__
        # Rename __nonzero__ function to __bool__ in python 3.
        __bool__ = __nonzero__
        del __nonzero__
    else:
        # Convert unicode to bytes in python 2.
        __str__ = lambda self: self.__unicode__().encode('utf-8')
    del sys


class CachedURL(URL):
    __slots__ = ()
    _cache = {}
    _cache_size = 20

    def __new__(cls, url=None, *args, **kwargs):
        # Cache only when parsing.
        if url is None:
            return URL.__new__(cls, None, *args, **kwargs)

        self = cls._cache.get(url)

        if self is None:
            if len(cls._cache) >= cls._cache_size:
                cls._cache.clear()

            # Construct and store.
            self = URL.__new__(cls, url)
            cls._cache[url] = self

        return self

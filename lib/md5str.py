# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division, print_function, unicode_literals)

import hashlib


def Md5str(string):
    _data = hashlib.md5()
    _data.update(string.encode("utf-8"))
    return _data.hexdigest()


if __name__ == '__main__':
    print(Md5str("-----BEGIN PRIVATE KEY-----" +
"MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDTIXwe6UR57pPk\n" +
"i+M1UEF6U0VLkCQu569Psjfd4cpxseE2YhvZwr7YZydQK2RNggIYyWsJy0qRnCbc\n" +
"4DUTzmzM4huY2ghb0nS6nwXrzXQGzHzxi2COyNsDbLj43FJDzSjJZSJ6dzVNHP0W\n" +
"y75rm4venTIyloinaHaQ2yNNcCPit0lzY+Xbttgyf0Asi3DrjUIHA4Vat4BOohoY\n" +
"Jxvm/p3iRfXnjhUWobhlsGx4BLQFlsdMZcjhbK09mDt5M3hCWsATso9C9aUU2Q9A\n" +
"AjWmpjAq/Rc/4aQinsYqKjxjLJEZV/7+mvwxUCTw1OehZ8KQLDmV8nAQhj4kCWY6\n" +
"JqX3gyKnAgMBAAECggEAPHFXoVnSmr2sZT+O+lJRjH2OVwWa9jqpu70ftUvQsx/j\n" +
"g7gulPblv/o4DQF/I5lWlFYFaLZkUK9NiOo/B76O81C/6dBxmCf19v9TqKAW2WNt\n" +
"WZE3QWlLGf3kLoqUmoh/ZrinWDwMbFkiM4Z8qz3Kmx6Rol3qHVMQroOt5Zt3Co49\n" +
"OJnZ62RjX2ZEzkQ2XxZLk9/PAeS4LLw7EJNheAsT6DCgJRt7CCgqQQs184zdAhTi\n" +
"73C/WKO4g2mGtBcRVfF1xS9FByGDPCFBnEURrVQAUPsg2WR/tASfdUV4KmTInDmI\n" +
"rMZRPM9/COBJoc4nxV23JD+YdzG4VEQhzgmKW6bSsQKBgQDt5RCPCO+WgFXPdS3h\n" +
"Q/FARg5nPvuC/NdZjjF9Rswr3uqyKMuKP6b4voQG8mmus86u+NJmcbIEewZLGlA8\n" +
"HM7mqM+sr381WKpg+3dm1zb1AZPDdSXoBpvnh21cJAojKVfQpGgJiMi2jG/ySENS\n" +
"dJLy323bTlVjRS+fGrNgq3ZOUwKBgQDjMvlVD1Qx5f0splK3+G5QzukgKLpL8ncd\n" +
"Cc2j7X/5g5TJI29V7lKdQIvJOevl+oMfD/wVG3IN4NxM6d/p2x4mjigyXTtLt90r\n" +
"4utik24QAQ7rpjO14WO55+c8imKZliKpjxJrQt3isZPVlRKDwzdNEmP88B20Vp3g\n" +
"htulgKXH3QKBgEaezGaZsX4NBOw8De2kXLbG1TnDEajV5BvawUg+Pxf66dMPlzSo\n" +
"JqoK7Gifh83r5Lw+cz8kG0OHPdwHqK/foXAJxvSteGbetl1p6Q0ncFIVMMdCPIl/\n" +
"hMKbilRjAntjp4TxeUzzRRoj4Iuc9hdBMepVd2g1/dUlUbi6lWtqGwmvAoGBALWL\n" +
"tdBSP2Tf8j4LaW24Be5sZ7xazwKA7M03WCr1TJ2Elw9iUUTI+xrMyOYycl2Cn+Pi\n" +
"UfxLwgd09pQ/Db1AagdE8LnN5ePLN+Apow1R4VDIh7OlSwy63YVf2VZ2/fLcFTaI\n" +
"LJ+o/sR2QTsZs4G2LCpZ16v18sZ3sBAJstm8wrvBAoGAa7DuhJGMziEVnEDAt3Ge\n" +
"S7p23EI3Kj2psLmCcASQO6lYPBLCZ1GcYy13XfDSH6jz2bnMoqz5uf0Df8OWfH7w\n" +
"uzTHH/PsjcaALsRAoWka/Sh3sPIBLSR15HdK1O9c0ram9XvC+9T99rU9Ojt7uesN\n" +
"ktMs4QWOeqxHt3TvJ/VR7yo=\n" +
"-----END PRIVATE KEY-----\n" +
"-----BEGIN PUBLIC KEY-----\n" +
"MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0yF8HulEee6T5IvjNVBB\n" +
"elNFS5AkLuevT7I33eHKcbHhNmIb2cK+2GcnUCtkTYICGMlrCctKkZwm3OA1E85s\n" +
"zOIbmNoIW9J0up8F6810Bsx88YtgjsjbA2y4+NxSQ80oyWUienc1TRz9Fsu+a5uL\n" +
"3p0yMpaIp2h2kNsjTXAj4rdJc2Pl27bYMn9ALItw641CBwOFWreATqIaGCcb5v6d\n" +
"4kX1544VFqG4ZbBseAS0BZbHTGXI4WytPZg7eTN4QlrAE7KPQvWlFNkPQAI1pqYw\n" +
"Kv0XP+GkIp7GKio8YyyRGVf+/pr8MVAk8NTnoWfCkCw5lfJwEIY+JAlmOial94Mi\n" +
"pwIDAQAB\n" +
"-----END PUBLIC KEY-----"))

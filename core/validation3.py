# _*_ coding:utf-8 _*_


"""
本模块，提供数据库字段在api层校验，检查不符合条件请求参数
检查model需要在submodels/子模块/db，对应的db连接处理下定义
格式如下：
adb = {
    "id": {"type": int, "notnull": False, "format": {">": 0, "<": 255, "in": [1, 2, 3, 4]}},
    "name": {"type": basestring, "notnull": False, "format": {">": 2, "<": 255, "re.match":"[a-z]"}},
    "desc": {"type": datetime.datetime},
    "status": {"type": bool},
    "ss": {"type": list, "notnull": True, "format": {"size":{">": 2, "<": 255}, "lenth":{">": 2, "<": 255},"in":[], "re.match":"[a-z]"}},
    "ggg": {"type": dict},
    "cv": {"type": "ip"},
    "xcss": {"type": "email"}
}
type字段为必须定义
format 定义简单的数值大小及字段长度的检查，in表示只允许固定的一些值，为列表类型
notnull 代表是否不为null， True表示不为None

注：数据库自增型字段不要定义，或自动生成的字段不要定义

:return 处理后的字段，如有不符合条件的字段，则会抛出ValueError异常
"""

from __future__ import (absolute_import, division, print_function, unicode_literals)

import datetime
import re

from lib.ip_helper import check_ip

import core.local_exceptions as exception_common

args_type = {
    "int": u"整数",
    "list": u"列表",
    "dict": u"json类型",
    "basestring": u"字符串类型",
    "str": u"字符串类型",
    "bool": u"布尔值",
    "datetime.datetime": u"时间类型",
    "unicode": u"字符串类型",
    "float": u"浮点数类型"
}


def validate_column_line(column):
    if re.match(r'^[0-9a-zA-Z_]{1,36}$', column):
        return True
    else:
        raise exception_common.RequestValidateError("不合法字段 %s" % column)


def validate_resource_id(rid):
    if re.match(r'^[.0-9a-zA-Z_-]{1,36}$', rid):
        return True
    else:
        raise exception_common.ResourceNotFoundError()


def format_type_to_chinese(type):
    for ixe in args_type.keys():
        if type == eval(ixe):
            return args_type.get(ixe)


def str_to_time(key, date_str):
    try:
        if ":" in date_str:
            return datetime.datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        else:
            return datetime.datetime.strptime(date_str, '%Y-%m-%d')
    except:
        raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，不是合法的时间" % date_str)


def validate_email_address(email_address):
    if re.match(r'^[.0-9a-zA-Z_-]{0,19}@[0-9a-zA-Z]{1,13}\.[comnet]{1,3}$', email_address):
        if email_address.endswith("com") or email_address.endswith("net") or email_address.endswith("cn"):
            return True

    raise exception_common.ValueValidateError(param="email", msg=u"非法值 %s，不是合法的邮件地址" % email_address)


class ValidateBase(object):
    @staticmethod
    def int_greater(value, key, validate_value):
        if validate_value is not None and not value > validate_value:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，参数值必须大于 %s" % (value, validate_value))

    @staticmethod
    def int_less(value, key, validate_value):
        if validate_value is not None and not value < validate_value:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，参数值必须小于 %s" % (value, validate_value))

    @staticmethod
    def int_equal_greater(value, key, validate_value):
        if validate_value is not None and not value >= validate_value:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，参数值必须大于等于 %s" % (value, validate_value))

    @staticmethod
    def int_equal_less(value, key, validate_value):
        if validate_value is not None and not value <= validate_value:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，参数值必须小于等于 %s" % (value, validate_value))

    @staticmethod
    def lenth_greater(value, key, validate_value):
        if validate_value is not None and not len(value) > validate_value:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，参数长度必须大于 %s" % (value, validate_value))

    @staticmethod
    def lenth_less(value, key, validate_value):
        if validate_value is not None and not len(value) < validate_value:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，参数长度必须小于 %s" % (value, validate_value))

    @staticmethod
    def lenth_equal_greater(value, key, validate_value):
        if validate_value is not None and not len(value) >= validate_value:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s, 参数长度必须大于等于 %s" % (value, validate_value))

    @staticmethod
    def lenth_equal_less(value, key, validate_value):
        if validate_value is not None and not len(value) <= validate_value:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，参数长度必须小于等于 %s" % (value, validate_value))

    @staticmethod
    def args_in(value, key, validate_value):
        if validate_value is not None and value not in validate_value:
            raise exception_common.ValueValidateError(param=key,
                                                      msg=u"非法值 %s，允许的参数值为：%s" % (value, bytes(validate_value)))

    @staticmethod
    def match_args(value, key, validate_value):
        if validate_value is not None and not re.match(r'%s' % validate_value, value):
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，不符合规则" % (value))

    @staticmethod
    def str_startswith(value, key, validate_value):
        if validate_value is not None and not value.startswith(validate_value):
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，需以 %s 开头" % (value, validate_value))

    @staticmethod
    def str_endswith(value, key, validate_value):
        if validate_value is not None and value.endswith(validate_value):
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，需以 %s 结束" % (value, validate_value))


map_int_validate = {">": ValidateBase.int_greater,
                    ">=": ValidateBase.int_equal_greater,
                    "<": ValidateBase.int_less,
                    "<=": ValidateBase.int_equal_less,
                    "in": ValidateBase.args_in}

map_string_validate = {">": ValidateBase.lenth_greater,
                       ">=": ValidateBase.lenth_equal_greater,
                       "<": ValidateBase.lenth_less,
                       "<=": ValidateBase.lenth_equal_less,
                       "in": ValidateBase.args_in,
                       "re.match": ValidateBase.match_args,
                       "startswith": ValidateBase.str_endswith,
                       "endswith": ValidateBase.str_endswith}


class ValidationArgs(object):
    @staticmethod
    def validate_time(key, value, validate_args):
        if isinstance(value, basestring):
            if "/" in value:
                value = value.replace("/", "-")
            value = str_to_time(key, value)
        elif isinstance(value, datetime.datetime):
            value = value
        else:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，不是合法的时间" % (value))
        return value

    @staticmethod
    def validate_int(key, value, validate_args):
        try:
            value = int(value)
        except:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s, 不是整数" % (value))

        format_data = validate_args.get("format", {})
        if format_data:
            for format_key, validate_value in format_data.items():
                func = map_int_validate.get(format_key)
                func(value, key, validate_value)

        return value

    @staticmethod
    def validate_float(key, value, validate_args):
        try:
            value = float(value)
        except:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s, 不是浮点数" % (value))

        format_data = validate_args.get("format", {})
        if format_data:
            for format_key, validate_value in format_data.items():
                func = map_int_validate.get(format_key)
                func(value, key, validate_value)

        return value

    @staticmethod
    def validate_string(key, value, validate_args):
        format_data = validate_args.get("format", {})
        if format_data:
            for format_key, validate_value in format_data.items():
                func = map_string_validate.get(format_key)
                func(value, key, validate_value)

        return value

    @staticmethod
    def validate_ipaddress(key, value, validate_args):
        res, msg = check_ip(value)
        if res:
            return value
        else:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，不是合法的IP地址" % (value))

    @staticmethod
    def validate_email(key, value, validate_args):
        res = validate_email_address(value)
        if res:
            return value
        else:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，不是合法的email地址" % (value))

    @staticmethod
    def validate_phone(key, value, validate_args):
        if not isinstance(value, basestring):
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，手机号需为字符串" % value)
        if re.match(r'1[3456789]\d{9}$', value) is not None:
            return value
        else:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，不是合法的手机号" % (value))

    @staticmethod
    def validate_list(key, value, validate_args):
        format_data = validate_args.get("format", {})
        if format_data:
            for format_key, format_value in format_data.items():
                if format_key in ["in", "re.match", "startswith", "endswith"]:
                    for t_value in value:
                        func = map_string_validate.get(format_key)
                        func(t_value, key, format_value)
                elif format_key == "lenth":
                    for t_key, t_value in format_value.items():
                        if t_key in [">", ">=", "<", "<="]:
                            func = map_string_validate.get(t_key)
                            func(value=value, key=key, validate_value=t_value)
                elif format_key == "size":
                    for size_key, size_value in format_value.items():
                        if size_key in [">", ">=", "<", "<="]:
                            for t_value in value:
                                if isinstance(t_value, basestring):
                                    func = map_string_validate.get(size_key)
                                elif isinstance(t_value, int):
                                    func = map_int_validate.get(size_key)
                                else:
                                    raise UnboundLocalError(u"know bond function")
                                func(value=t_value, key=key, validate_value=size_value)

        return value

    @staticmethod
    def validate_bool(key, value, validate_args):
        return value

    @staticmethod
    def validate_dict(key, value, validate_args):
        return value


map_validate = {datetime.datetime: ValidationArgs.validate_time,
                int: ValidationArgs.validate_int,
                float: ValidationArgs.validate_float,
                basestring: ValidationArgs.validate_string,
                "ip": ValidationArgs.validate_ipaddress,
                "email": ValidationArgs.validate_email,
                "phone": ValidationArgs.validate_phone,
                list: ValidationArgs.validate_list,
                bool: ValidationArgs.validate_bool,
                dict: ValidationArgs.validate_dict}


def check_args(key, value, model):
    format_type = model.get("type")
    notnull = model.get("notnull", False)
    if value is None:
        if notnull:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值，不允许为空")
        else:
            return value

    if format_type in ["ip", "email", "phone", datetime.datetime, int]:
        func = map_validate.get(format_type)
        return func(key, value, model)
    else:
        if isinstance(value, format_type):
            func = map_validate.get(format_type)
            return func(key, value, model)
        else:
            raise exception_common.ValueValidateError(param=key, msg=u"非法值 %s，传入类型为 %s，合法类型为：%s"
                                                                     % (value, format_type_to_chinese(type(value)),
                                                                        format_type_to_chinese(format_type)))



if __name__ == '__main__':
    adb = {
        "id": {"type": int, "notnull": False, "format": {">": 0, "<": 255, "in": [1, 2, 3, 4]}},
        "name": {"type": basestring, "notnull": False, "format": {">": 2, "<": 255}},
        "desc": {"type": datetime.datetime},
        "status": {"type": bool},
        "ss": {"type": list, "notnull": True, "format": {"size": {">": 1, "<=": 3}}},
        "ggg": {"type": dict},
        "xxx": {"type": "ip"},
        "fff": {"type": "email", "format": {}, "validate": {"aa": 122}}
    }
    data = {"id": None, "name": "trs", "desc": "2000/01/08", "ss": [], "xxx": "192.168.137.1", "ggg": {},
            "fff": "ex-sksk001@cmft.com"}
    gsss = model_via_check(data, adb)
    print(gsss)

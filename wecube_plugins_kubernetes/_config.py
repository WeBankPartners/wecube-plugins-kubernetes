# coding : utf-8

from lib.ConfigReader import Config

# ---------------------default setting --------------------
DEBUG = Config.getBool("DEFAULT", "debug", default=False)
PORT = Config.getInt("DEFAULT", "serverport", default=8090)

# ---------------------log setting --------------------
LOG_NAME = Config.get("LOG", "name", default="service.log")
LOG_LEVEL = Config.get("LOG", "level", default="INFO")
LOG_MAX_SIZE = Config.getInt("LOG", "max_size", default="200") * 1024 * 1024
LOG_BACKUP = Config.getInt("LOG", "backup_count", default=3)
LOG_MSG_MAX_LEN = Config.getInt("LOG", "msg_max_len", default=2048)

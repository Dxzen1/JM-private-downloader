# 第三方软件声明

## JMComic-Crawler-Python / jmcomic

- 上游项目：`hect0x7/JMComic-Crawler-Python`
- 源码地址：https://github.com/hect0x7/JMComic-Crawler-Python
- Python 包：https://pypi.org/project/jmcomic/
- 上游作者：`hect0x7`
- 上游许可证：MIT License
- 本项目中的用途：通过公开的 Python 包接口创建下载配置并调用漫画下载功能。

本仓库未内嵌或重新发布 JMComic-Crawler-Python 的源代码，而是在安装时通过 `requirements.txt` 获取 `jmcomic` 依赖。该第三方项目的版权和商标归各自权利人所有；使用时请同时遵守其许可证、目标服务条款及适用法律。

本声明仅用于标明技术依赖和脚本来源，不表示本项目由上游作者或 JM 官方认可、维护或提供支持。

## gallery-dl

- 上游项目及作者：`mikf/gallery-dl`，Mike Fährmann
- 当前上游源码：https://codeberg.org/mikf/gallery-dl
- Python 包：https://pypi.org/project/gallery-dl/
- 上游许可证：GNU General Public License v2.0 only（GPL-2.0-only）
- 本项目中的用途：通过独立子进程调用命令行接口，下载 E-Hentai / ExHentai 画廊图片，再由门户生成 ZIP。

本仓库未内嵌或修改 gallery-dl 的源码，安装依赖时获取官方 PyPI 包。分发包含该组件的容器或其他副本时，应同时遵守其许可证及对应源代码提供要求。以上集成不表示目标网站或上游作者认可本项目。

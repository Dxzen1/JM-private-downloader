# JM / E 私人下载站

一个适合手机使用的单用户下载门户：选择 JM、E-Hentai 或 ExHentai，输入 JM 编号或粘贴 E 站完整画廊链接，服务器后台下载并生成 ZIP，只向已登录用户提供下载。

> 使用者应确保已取得所需授权，并只在授权范围内使用；同时请遵守资源版权、内容分发规则和服务器所在地的法律要求。

## 脚本来源与致谢

本项目的下载能力通过 Python 依赖 [`jmcomic`](https://pypi.org/project/jmcomic/) 实现，其上游源码为 [hect0x7/JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python)，作者为 `hect0x7`，采用 MIT License。

本仓库没有冒充或声称隶属于 JM 官方，也不是官方 SDK。仓库中的 FastAPI 门户、登录、任务队列、ZIP 打包、Docker 与宝塔部署层是围绕上述依赖编写的独立集成代码；更完整的第三方说明见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

E-Hentai / ExHentai 使用 [`gallery-dl`](https://pypi.org/project/gallery-dl/)，上游为 [mikf/gallery-dl（Codeberg）](https://codeberg.org/mikf/gallery-dl)。使用官方 PyPI 发行版；GitHub 镜像已移除部分站点的支持。

## 功能

- 单用户登录与安全会话 Cookie
- JM 编号及 E-Hentai / ExHentai 完整画廊链接校验，按来源抑制重复任务
- SQLite 持久化任务队列，中断任务标为失败，可手动重试
- 后台串行下载，避免对上游造成突发压力
- 自动生成 ZIP，同时提供 CBZ 下载，可导入漫画阅读器
- 下载任务在独立进程中运行，保留线上内存和超时限制
- 失败任务重试、手动删除、自动过期清理
- 存储空间配额
- CSRF 防护、安全响应头、下载路径校验
- `stub` 模拟模式，用于上线前测试

## 服务器要求

- 阿里云海外 ECS
- 宝塔面板
- Docker 与 Docker Compose
- 一个解析到服务器公网 IP 的域名
- 建议至少 2 核 CPU、2 GB 内存，并准备足够的数据盘空间

## 一、上传项目

把整个项目目录上传到服务器，例如：

```text
/www/wwwroot/jm-private-portal
```

在宝塔终端进入该目录：

```bash
cd /www/wwwroot/jm-private-portal
```

## 二、创建配置

复制环境变量模板：

```bash
cp .env.example .env
```

生成会话密钥：

```bash
openssl rand -hex 32
```

编辑 `.env`，至少替换：

```dotenv
ADMIN_USERNAME=你的登录用户名
ADMIN_PASSWORD=至少12位的独立强密码
SESSION_SECRET=刚生成的64位十六进制字符串
SECURE_COOKIE=true
JM_PROVIDER=jmcomic
MAX_STORAGE_GB=20
RETENTION_HOURS=168
```

`RETENTION_HOURS=168` 表示完成文件保留七天。过期任务和 ZIP 会自动删除。

## 三、配置授权参数

复制示例：

```bash
cp secrets/jm-option.example.yml secrets/jm-option.yml
```

编辑 `secrets/jm-option.yml`，按照你获得的官方授权填写账号、Token、允许的客户端实现和并发限制。不要修改或填写 `dir_rule.base_dir`，网站会为每个任务自动设置隔离目录。

配置文件会以只读方式挂载到容器内，不会通过网页返回。不要把 `.env` 或真实的 `jm-option.yml` 发给他人。

## 四、先用模拟模式验证

第一次上线建议在 `.env` 中设置：

```dotenv
JM_PROVIDER=stub
EH_PROVIDER=stub
SECURE_COOKIE=false
```

启动：

```bash
docker compose up -d --build
```

在服务器本机检查：

```bash
curl http://127.0.0.1:18080/healthz
```

应该返回：

```json
{"status":"ok"}
```

## 五、在宝塔创建站点

1. 打开宝塔的“网站”，添加你的域名。
2. 申请并启用 Let's Encrypt SSL，开启“强制 HTTPS”。
3. 在站点的“配置文件”或“反向代理”中，把所有请求代理至 `http://127.0.0.1:18080`。
4. `deploy/baota-nginx.conf` 提供了可直接参考的 Nginx 配置。
5. 阿里云安全组只需公开 TCP `80` 和 `443`；不要公开 `18080`。

通过手机访问域名，登录后提交测试 ID。模拟任务会很快完成并出现“下载 ZIP”按钮。

## 六、启用 JM 下载组件

确认 HTTPS、登录、ZIP 下载和删除均正常后，将 `.env` 改为：

```dotenv
JM_PROVIDER=jmcomic
SECURE_COOKIE=true
```

重新创建容器：

```bash
docker compose up -d --build --force-recreate
```

查看运行日志：

```bash
docker compose logs -f --tail=100 portal
```

日志中不会主动打印网站登录密码，但上游组件可能输出请求信息，因此不要公开日志。

## 七、启用 E-Hentai / ExHentai

E 站必须输入完整画廊链接，单独的数字编号缺少访问令牌，无法下载。例如：

```text
https://e-hentai.org/g/123456/0123456789/
https://exhentai.org/g/123456/0123456789/
```

选择任一 E 站来源后粘贴链接，系统按链接域名识别实际来源；JM 来源仍只接受 JM 编号。

公开的 E-Hentai 画廊可以不配置登录信息。ExHentai 必须使用具有访问权限的账号 Cookie：

```bash
cp secrets/eh-option.example.json secrets/eh-option.json
```

在服务器编辑 `secrets/eh-option.json`，填写你已登录浏览器中的 `ipb_member_id`、`ipb_pass_hash` 和 `igneous`。这些值只保存在服务器配置中，不需要通过下载站网页提交。账号是否能访问具体画廊，仍取决于站点权限和 Cookie 的有效性。

也可以把 cookies.txt 格式的浏览器 Cookie 文件放在 `secrets/eh-cookies.txt`，将配置改成：

```json
{
  "extractor": {
    "exhentai": {
      "cookies": "/run/secrets/eh-cookies.txt",
      "original": false
    }
  }
}
```

Cookie 文件须包含目标域名的登录 Cookie，ExHentai 使用 `exhentai.org` 域名的 Cookie。整个 `secrets/` 目录以只读方式挂载，下载组件不会回写 Cookie；容器内运行用户须对配置和 Cookie 文件有读取权限。真实配置和 Cookie 文件已加入 Git 忽略规则，请勿提交或公开。

门户读取 `extractor.exhentai` 中的 `cookies`、`original`、`proxy` 和 `user-agent`；输出目录和文件名由门户统一管理，其他 gallery-dl 选项不导入。默认 `original=false` 下载站点提供的浏览版本；设为 `true` 可请求账号有权下载的原图。遇到站点额度或访问限制时任务失败，可稍后手动重试，不会自动花费 GP 重置额度。

在 `.env` 中启用真实下载：

```dotenv
EH_PROVIDER=gallery-dl
EH_OPTION_PATH=/run/secrets/eh-option.json
EH_TIMEOUT_SECONDS=7200
```

`JM_PROVIDER` 与 `EH_PROVIDER` 相互独立，E 站单任务默认最多运行两小时。更新后重建容器：

```bash
docker compose up -d --build --force-recreate
```

旧版数据库会在启动时自动添加来源字段，已有任务默认归为 JM，原 ZIP 和任务记录保留。备份原数据库后再升级即可，无须手动修改 SQLite。

## 日常管理

查看状态：

```bash
docker compose ps
```

更新代码后重建：

```bash
docker compose up -d --build
```

停止：

```bash
docker compose down
```

备份以下目录：

```text
data/       SQLite 任务数据库
downloads/ 已生成的 ZIP
.env        网站配置和登录凭据
secrets/    JM 配置和 E 站 Cookie 配置
```

## 安全建议

- 宝塔面板端口与 SSH 端口只允许你的固定 IP。
- 为宝塔开启两步验证，不要与网站共用密码。
- 不要将 `downloads` 配置为公开静态目录；应用会在登录校验后返回文件。
- 定期更新基础镜像与依赖，并检查服务器磁盘空间。
- 上游授权被撤销或发生异常时，立即把 `JM_PROVIDER` 改为 `stub` 并重启。
- 本项目设计为个人单用户、小并发服务，不应作为公开下载站。

## 本地测试

```bash
python -m venv .venv
```

```bash
. .venv/bin/activate
```

```bash
pip install -r requirements-dev.txt
```

```bash
pytest -q
```

## 常见问题

### 登录成功后又跳回登录页

如果尚未配置 HTTPS，临时设置 `SECURE_COOKIE=false`；正式上线并启用 HTTPS 后必须改回 `true`。

### 任务失败并提示找不到配置文件

确认 `secrets/jm-option.yml` 存在，且不是示例文件名。然后运行：

```bash
docker compose restart portal
```

### ZIP 很大，手机下载中断

确认宝塔/Nginx 未限制响应大小和超时时间。应用的文件响应支持现代浏览器下载；若未来需要分离存储，可将适配器扩展到对象存储。

### 为什么只能运行一个应用 worker

后台任务队列当前使用 SQLite 抢占与单消费者模式。保持 Uvicorn `--workers 1` 可避免同一服务器上出现多套清理循环；后台线程等待独立下载进程，不会阻塞页面访问。JM 保留 `TASK_MEMORY_MB`（默认 512 MB）和 `TASK_TIMEOUT_SECONDS`（默认 900 秒）限制；E 站使用独立进程和同样的内存限制，超时由 `EH_TIMEOUT_SECONDS` 控制。

### CBZ 下载

已完成任务可选择“下载 CBZ”或“下载 ZIP”。两种下载返回同一份已保存压缩包的原始字节，只改变下载扩展名和响应类型，不重新压缩、不改变图片质量、不增加漫画副本。

`/tasks/{task_id}/download` 默认返回 ZIP，`/tasks/{task_id}/download?format=cbz` 返回 CBZ。两种格式均要求登录，并使用相同的完成状态、文件存在及下载目录边界检查。

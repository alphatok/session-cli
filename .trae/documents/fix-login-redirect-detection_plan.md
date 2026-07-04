# CDP 分析 & 修复：登录重定向检测

## CDP 分析结论

### 复现问题

通过 CDP 导航到 `https://chat.deepseek.com/a/chat/s/3a70de02-a7f0-4e0b-9ec9-4447873804b4`：

| 状态 | 实际 URL | Cookie | localStorage auth tokens |
|------|----------|--------|--------------------------|
| **未登录** | `https://chat.deepseek.com/sign_in`（被重定向） | 2 个（smidV2, thumbcache） | userToken=null, settingsJwt=null |
| **已登录** | `https://chat.deepseek.com/a/chat/s/...`（正常） | 2 个（smidV2, thumbcache） | userToken=有效值, tea_cache_tokens=有效值 |

### 根因

`_grab_cookies_impl` 在 `navigate_page` 之后不检测当前页面 URL 是否已被重定向，直接执行 JS 采集 Cookie。当用户未登录时，页面被重定向到 `/sign_in`，采集到无效数据。

## 检测策略

**对比 URL 一致**：导航后提取当前页面 URL，与用户提供的 `navigate_url` 对比。若不一致，说明页面发生了重定向（大概率是登录页），直接报错。

这种方式比匹配登录关键词模式更通用，无需维护关键词列表，适用于所有站点。

## 修改文件

仅修改：`core/mcp.py`

## 修改步骤

### 步骤 1：新增 URL 提取辅助函数

在 `core/mcp.py` 中新增 `_extract_current_url(text: str) -> Optional[str]` 函数，从 `navigate_page` 返回的 Markdown 文本中提取当前页面 URL。

导航返回格式：
```
Successfully navigated to https://...
## Pages
1: Page Title (https://actual-page-url) [selected]
```

解析策略：用正则匹配 `(https?://[^\s)]+)` 提取最后一个 URL（即当前选中页面的 URL）。

### 步骤 2：导航后对比 URL 一致性

在 `_grab_cookies_impl` 中，`navigate_page` 调用后：

1. 从响应中提取当前页面 URL（`current_url`）
2. 对比 `current_url` 与 `navigate_url`（同时去掉末尾的 `/` 和 `#` 后对比）
3. 若不一致，抛出 `RuntimeError(f"页面被重定向: {current_url}，请确认已在浏览器中登录该站点后重试")`

### 步骤 3：降级处理

若无法从响应中提取 URL（响应格式异常），跳过检测，沿用原有逻辑（不阻塞正常流程）。

## 对比示例

```
navigate_url = "https://chat.deepseek.com/a/chat/s/3a70de02-..."
current_url  = "https://chat.deepseek.com/sign_in"
→ 不一致 → 抛出错误

navigate_url = "https://chat.deepseek.com/a/chat/s/3a70de02-..."
current_url  = "https://chat.deepseek.com/a/chat/s/3a70de02-..."
→ 一致 → 正常继续

navigate_url = "https://yuanbao.tencent.com"
current_url  = "https://yuanbao.tencent.com/"
→ 去掉末尾 / 后一致 → 正常继续
```

## 验证方式

1. 未登录 + `https://chat.deepseek.com/a/chat/s/...` → 抛出 "页面被重定向到 https://chat.deepseek.com/sign_in"
2. 已登录 + `https://chat.deepseek.com/a/chat/s/...` → 正常完成
3. 已登录 + 其他站点（如 `yuanbao.tencent.com`）→ 正常完成
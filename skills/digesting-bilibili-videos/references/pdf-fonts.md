# PDF：中文为什么会「显示正常但搜不到」

`lib/pdftext.py` 和 `lib/pdfbook.py` 背后的踩坑结论。换字体前后都读这份。

## 内容

- 康熙部首区：最阴的那个坑
- 换字体后必须跑的验证命令
- 别用系统字体
- 变量字体要先定格成静态 TTF
- 缺一个字形就能毁掉整本

## 康熙部首区：最阴的那个坑

很多中文字体能**正常显示**，但会把常用字映射到**康熙部首区**（U+2F00–2FDF）。字形渲染是对的，肉眼完全看不出问题——但 PDF 内搜索和复制会失效，因为文本层里存的是部首码位，不是汉字码位。

选定 Noto Sans SC 就是为这个。`BILI_SKILLS_FONT` 可以换，但换完必须验。

## 换字体后必须跑的验证命令

**肉眼看「中文显示正常」不等于没问题。** 抽一页文本，确认该区字符数为 **0**：

```bash
pip install pypdf     # 只有这一步要它，doctor 不查这个依赖
python3 -c "from pypdf import PdfReader; t=''.join(p.extract_text() or '' for p in PdfReader('out/xxx-outline.pdf').pages); print('康熙部首:', sum(0x2F00<=ord(c)<=0x2FDF for c in t))"
```

输出必须是 `康熙部首: 0`。不是 0 就说明这个字体不能用。

## 别用系统字体

macOS 的 `PingFang.ttc` 和 `Hiragino Sans GB.ttc` 是 PostScript(CFF) 轮廓，很多 PDF 库直接解析不了；`.ttc` 还得指定 subfontIndex。

更根本的问题：依赖系统字体的话，三个平台出来的 PDF 长得都不一样。所以字体随 skill 自带（`assets/fonts/NotoSansSC.ttf`，按 SIL OFL 1.1 分发，许可证在旁边的 `OFL.txt`）。

## 变量字体要先定格成静态 TTF

fpdf2 吃静态最稳。`pdftext.instance()` 用 fontTools 定格到 400/700 两个字重，缓存在 `~/.cache/bili-skills/fonts/`（`BILI_SKILLS_CACHE` 可改），只算一次。

## 缺一个字形就能毁掉整本

fpdf2 遇到字体没有的码位（多半是标题里的 emoji）会在 `encode_text` 抛 `TypeError`，整本 PDF 就出不来了。

`pdftext.safe()` 按 cmap 静默摘掉未覆盖的字符。**测宽和落笔必须共用同一条路径**——否则排版会按摘除前的宽度算，行宽对不上。

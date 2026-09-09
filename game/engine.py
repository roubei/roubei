#!/usr/bin/env python3
"""roubei/roubei — Issue 驱动的井字棋引擎。

访客点击 README 里的格子 → 打开一个预填标题的 Issue → 本脚本
落子、由仓库 AI 应手、重绘 README、关闭 Issue。

用法:
    engine.py --title <issue title> --issue <n> --actor <login>
    engine.py --render-only
"""
import argparse
import datetime
import json
import os
import random
import re
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "game", "state.json")
README_PATH = os.path.join(ROOT, "README.md")
HEADER_PATH = os.path.join(ROOT, "parts", "header.md")
FOOTER_PATH = os.path.join(ROOT, "parts", "footer.md")

REPO = os.environ.get("GITHUB_REPOSITORY", "roubei/roubei")

HUMAN, BOT = "H", "B"
GLYPH = {HUMAN: "●", BOT: "✕"}
LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8),
         (0, 3, 6), (1, 4, 7), (2, 5, 8),
         (0, 4, 8), (2, 4, 6)]
BLUNDER_RATE = 0.22          # 仓库 AI 的失手概率 —— 没有它就没人赢得了


# ── 状态 ────────────────────────────────────────────────────────────────

def new_state():
    return {
        "game_id": 1,
        "board": [""] * 9,
        "move_no": 0,
        "finished": False,
        "result": None,
        "win_line": None,
        "players": [],
        "stats": {"human": 0, "bot": 0, "draw": 0},
        "hall": [],
        "log": [],
    }


def load_state():
    if not os.path.exists(STATE_PATH):
        return new_state()
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(s):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
        f.write("\n")


def reset_board(s):
    s["game_id"] += 1
    s["board"] = [""] * 9
    s["move_no"] = 0
    s["finished"] = False
    s["result"] = None
    s["win_line"] = None
    s["players"] = []


# ── 规则 ────────────────────────────────────────────────────────────────

def winner(board):
    for line in LINES:
        a, b, c = line
        if board[a] and board[a] == board[b] == board[c]:
            return board[a], list(line)
    return None, None


def legal(board):
    return [i for i, v in enumerate(board) if not v]


def minimax(board, player, depth=0):
    """返回 (分数, 落点)，分数以 BOT 视角计。"""
    w, _ = winner(board)
    if w == BOT:
        return 10 - depth, None
    if w == HUMAN:
        return depth - 10, None
    moves = legal(board)
    if not moves:
        return 0, None

    best_score = None
    best_move = None
    for m in moves:
        board[m] = player
        score, _ = minimax(board, HUMAN if player == BOT else BOT, depth + 1)
        board[m] = ""
        if best_score is None \
           or (player == BOT and score > best_score) \
           or (player == HUMAN and score < best_score):
            best_score, best_move = score, m
    return best_score, best_move


def bot_move(board, seed):
    """立刻能赢就赢；否则按 BLUNDER_RATE 的概率失手，其余时候走最优解。"""
    moves = legal(board)
    for m in moves:
        board[m] = BOT
        if winner(board)[0] == BOT:
            board[m] = ""
            return m
        board[m] = ""

    rnd = random.Random(seed * 7919 + len(moves))
    if len(moves) > 1 and rnd.random() < BLUNDER_RATE:
        return rnd.choice(moves)

    return minimax(list(board), BOT)[1]


# ── 渲染 ────────────────────────────────────────────────────────────────

def move_url(cell, s):
    title = "play-{}-g{}-m{}".format(cell + 1, s["game_id"], s["move_no"])
    body = "提交即落子，正文不用改。"
    return "https://github.com/{}/issues/new?title={}&body={}".format(
        REPO, urllib.parse.quote(title), urllib.parse.quote(body))


def newgame_url(s):
    title = "newgame-g{}".format(s["game_id"])
    body = "提交即开新一局。"
    return "https://github.com/{}/issues/new?title={}&body={}".format(
        REPO, urllib.parse.quote(title), urllib.parse.quote(body))


def render_board(s):
    rows = []
    for r in range(3):
        cells = []
        for c in range(3):
            i = r * 3 + c
            v = s["board"][i]
            if v:
                mark = GLYPH[v]
                if s["win_line"] and i in s["win_line"]:
                    inner = "<b>{}</b>".format(mark)
                else:
                    inner = mark
            elif s["finished"]:
                inner = "<sub>·</sub>"
            else:
                inner = '<a href="{}" title="落在第 {} 格">＋</a>'.format(
                    move_url(i, s), i + 1)
            cells.append(
                '<td align="center" width="76" height="64">{}</td>'.format(inner))
        rows.append("<tr>{}</tr>".format("".join(cells)))
    return ("<table>\n" + "\n".join(rows) + "\n</table>")


def render_status(s):
    if not s["finished"]:
        n = 9 - len(legal(s["board"]))
        return "**轮到你。** 点任意 <code>＋</code> 落子 —— 你执 ● ，仓库执 ✕ 。" \
               "　<sub>第 {} 手</sub>".format(n + 1)
    if s["result"] == "human":
        who = s["players"][-1] if s["players"] else "路人"
        return "### ● 人类胜。 @{} 拿下第 {} 局。\n\n" \
               "<a href=\"{}\"><b>▶ 开新一局</b></a>".format(
                   who, s["game_id"], newgame_url(s))
    if s["result"] == "bot":
        return "### ✕ 仓库胜。 第 {} 局收在这里。\n\n" \
               "<a href=\"{}\"><b>▶ 再来一局</b></a>".format(
                   s["game_id"], newgame_url(s))
    return "### ─ 平局。 第 {} 局无人越线。\n\n" \
           "<a href=\"{}\"><b>▶ 再来一局</b></a>".format(
               s["game_id"], newgame_url(s))


def render_hall(s):
    if not s["hall"]:
        return "_还没有人赢过。名字空着。_"
        
    seen = {}
    for h in s["hall"]:
        seen[h["user"]] = seen.get(h["user"], 0) + 1
    ranked = sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
    return " · ".join(
        "[@{0}](https://github.com/{0}){1}".format(u, "" if n == 1 else " ×{}".format(n))
        for u, n in ranked)


def render_log(s):
    if not s["log"]:
        return "_暂无。_"
    return "\n".join("- " + line for line in s["log"][-10:][::-1])


def read_part(path, fallback=""):
    """读入可自由编辑的文案片段，顺手剔掉给作者看的 HTML 注释。"""
    if not os.path.exists(path):
        return fallback
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return text.strip("\n").strip()


def render_readme(s):
    st = s["stats"]
    total = st["human"] + st["bot"] + st["draw"]
    players = " ".join("[@{0}](https://github.com/{0})".format(p)
                       for p in dict.fromkeys(s["players"]))

    doc = []
    doc.append(read_part(HEADER_PATH))
    doc.append("")
    doc.append("<div align=\"center\">")
    doc.append("")
    doc.append("### 井字棋 · 全网 vs 这个仓库")
    doc.append("")
    doc.append("<sub>第 {} 局 · 人类 {} 胜 {} 平 {} 负 · 共 {} 局</sub>".format(
        s["game_id"], st["human"], st["draw"], st["bot"], total))
    doc.append("")
    doc.append(render_board(s))
    doc.append("")
    doc.append(render_status(s))
    doc.append("")
    if players:
        doc.append("<sub>本局执 ● 者：{}</sub>".format(players))
        doc.append("")
    doc.append("</div>")
    doc.append("")
    doc.append("<details>")
    doc.append("<summary>怎么玩（点开）</summary>")
    doc.append("")
    doc.append("1. 点棋盘上任意一个 `＋`。GitHub 会打开一个**标题已经填好**的新 issue。")
    doc.append("2. 什么都不用改，直接提交。")
    doc.append("3. 半分钟内，机器人替你落子、应一手、重绘这个页面，并关掉那条 issue。")
    doc.append("")
    doc.append("棋局是**共享**的：任何人都可以接着上一位访客的局面走下一手。")
    doc.append("仓库这一侧由 minimax 驱动，但留了 22% 的失手率 —— 所以是能赢的。")
    doc.append("看到「棋盘已更新」，说明你手上是缓存页面，刷新后再点。")
    doc.append("")
    doc.append("</details>")
    doc.append("")
    doc.append("**名人堂** — 赢过这个仓库的人")
    doc.append("")
    doc.append(render_hall(s))
    doc.append("")
    doc.append("<details>")
    doc.append("<summary>战报</summary>")
    doc.append("")
    doc.append(render_log(s))
    doc.append("")
    doc.append("</details>")
    doc.append("")
    footer = read_part(FOOTER_PATH)
    if footer:
        doc.append("---")
        doc.append("")
        doc.append(footer)
        doc.append("")

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(doc).rstrip("\n") + "\n")


# ── 一手棋 ──────────────────────────────────────────────────────────────

def today():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


def settle(s, actor):
    """判定局面，必要时记账。返回给 issue 的回复文案；未结束返回 None。"""
    w, line = winner(s["board"])
    if w:
        s["finished"] = True
        s["win_line"] = line
        s["result"] = "human" if w == HUMAN else "bot"
        s["stats"]["human" if w == HUMAN else "bot"] += 1
        if w == HUMAN:
            s["hall"].append({"user": actor, "game": s["game_id"], "date": today()})
            s["log"].append("第 {} 局 · @{} 胜 · {}".format(s["game_id"], actor, today()))
            return "● 你赢了。第 {} 局归你，名字已经进名人堂。".format(s["game_id"])
        s["log"].append("第 {} 局 · 仓库胜 · {}".format(s["game_id"], today()))
        return "✕ 仓库拿下这局。回主页开新一局。"
    if not legal(s["board"]):
        s["finished"] = True
        s["result"] = "draw"
        s["stats"]["draw"] += 1
        s["log"].append("第 {} 局 · 平局 · {}".format(s["game_id"], today()))
        return "─ 平局。回主页开新一局。"
    return None


def handle(title, issue_no, actor):
    s = load_state()

    m = re.fullmatch(r"newgame-g(\d+)", title.strip())
    if m:
        if not s["finished"] and s["move_no"] > 0:
            render_readme(s)
            save_state(s)
            return "当前这局还没下完，回主页接着走。"
        reset_board(s)
        save_state(s)
        render_readme(s)
        return "新的一局开好了 —— 第 {} 局。回主页落第一手。".format(s["game_id"])

    m = re.fullmatch(r"play-([1-9])-g(\d+)-m(\d+)", title.strip())
    if not m:
        return None      # 不是游戏 issue，交给人处理

    cell = int(m.group(1)) - 1
    gid, mv = int(m.group(2)), int(m.group(3))

    if s["finished"]:
        render_readme(s)
        return "第 {} 局已经结束了。回主页点「开新一局」。".format(s["game_id"])
    if gid != s["game_id"] or mv != s["move_no"] or s["board"][cell]:
        render_readme(s)
        return ("棋盘已经变了 —— 你看到的是缓存页面（有人比你先落子）。"
                "刷新主页，再点一次。")

    s["board"][cell] = HUMAN
    s["move_no"] += 1
    if actor not in s["players"]:
        s["players"].append(actor)

    reply = settle(s, actor)
    if reply is None:
        b = bot_move(s["board"], issue_no)
        if b is not None:
            s["board"][b] = BOT
            s["move_no"] += 1
        reply = settle(s, actor)
        if reply is None:
            reply = "落子第 {} 格。仓库应了第 {} 格 —— 回主页看棋盘，接着走。".format(
                cell + 1, (b or 0) + 1)

    save_state(s)
    render_readme(s)
    return reply


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="")
    ap.add_argument("--issue", type=int, default=0)
    ap.add_argument("--actor", default="anonymous")
    ap.add_argument("--render-only", action="store_true")
    a = ap.parse_args()

    if a.render_only:
        s = load_state()
        save_state(s)
        render_readme(s)
        print("rendered")
        return

    reply = handle(a.title, a.issue, a.actor)
    if reply is None:
        print("SKIP")
    else:
        print(reply)


if __name__ == "__main__":
    main()

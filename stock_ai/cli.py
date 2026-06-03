from __future__ import annotations

import argparse
from pathlib import Path

from .backtest import BacktestConfig, run_backtest
from .factors import load_market_csv
from .notifier import ReliableWeChatSender
from .optimizer import optimize_strategy
from .reports import format_trade_alerts, format_wechat_summary, save_backtest_outputs, save_optimization_outputs
from .strategy import StrategyConfig, select_candidates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stock-ai", description="A-share factor selection, paper trading, and backtesting.")
    sub = parser.add_subparsers(dest="command", required=True)

    screen = sub.add_parser("screen", help="select current stock candidates")
    screen.add_argument("--csv", required=True)
    screen.add_argument("--as-of", required=True)
    screen.add_argument("--top-n", type=int, default=3)
    screen.add_argument("--min-score", type=float, default=45)
    screen.add_argument("--output", default="output/stock_ai/candidates.csv")

    backtest = sub.add_parser("backtest", help="run one simulated trading backtest")
    backtest.add_argument("--csv", required=True)
    backtest.add_argument("--start-date", required=True)
    backtest.add_argument("--end-date", required=True)
    backtest.add_argument("--initial-cash", type=float, default=1_000_000)
    backtest.add_argument("--top-n", type=int, default=3)
    backtest.add_argument("--min-score", type=float, default=45)
    backtest.add_argument("--max-hold-days", type=int, default=20)
    backtest.add_argument("--output-dir", default="output/stock_ai/backtest")
    backtest.add_argument("--wechat", action="store_true")
    backtest.add_argument("--cc-connect", default="/Users/lan/.nvm/versions/node/v23.7.0/bin/cc-connect")
    backtest.add_argument("--wechat-project", default="daily-market-news")
    backtest.add_argument("--wechat-session", default="weixin:dm:o9cq808Zm6pkjw0mJxDT8kaN4pKo@im.wechat")
    backtest.add_argument("--wechat-outbox", default="output/stock_ai/wechat_outbox")

    opt = sub.add_parser("optimize", help="search strategy parameters and save the best run")
    opt.add_argument("--csv", required=True)
    opt.add_argument("--start-date", required=True)
    opt.add_argument("--end-date", required=True)
    opt.add_argument("--initial-cash", type=float, default=1_000_000)
    opt.add_argument("--output-dir", default="output/stock_ai/optimization")

    daily = sub.add_parser("daily-summary", help="run backtest through today and send a WeChat summary")
    daily.add_argument("--csv", required=True)
    daily.add_argument("--start-date", required=True)
    daily.add_argument("--end-date", required=True)
    daily.add_argument("--output-dir", default="output/stock_ai/daily")
    daily.add_argument("--cc-connect", default="/Users/lan/.nvm/versions/node/v23.7.0/bin/cc-connect")
    daily.add_argument("--wechat-project", default="daily-market-news")
    daily.add_argument("--wechat-session", default="weixin:dm:o9cq808Zm6pkjw0mJxDT8kaN4pKo@im.wechat")
    daily.add_argument("--wechat-outbox", default="output/stock_ai/wechat_outbox")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    bars = load_market_csv(args.csv)
    if args.command == "screen":
        candidates = select_candidates(bars, args.as_of, StrategyConfig(args.top_n, args.min_score))
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        candidates.to_csv(output, index=False)
        print(f"saved {len(candidates)} candidates to {output}")
        return 0
    if args.command == "backtest":
        result = run_backtest(
            bars,
            BacktestConfig(
                start_date=args.start_date,
                end_date=args.end_date,
                initial_cash=args.initial_cash,
                top_n=args.top_n,
                min_score=args.min_score,
                max_hold_days=args.max_hold_days,
            ),
        )
        save_backtest_outputs(result, Path(args.output_dir))
        print(format_wechat_summary(result))
        if args.wechat:
            sender = ReliableWeChatSender(
                cc_connect=Path(args.cc_connect),
                project=args.wechat_project,
                session=args.wechat_session,
                outbox_dir=Path(args.wechat_outbox),
            )
            flushed = sender.flush_outbox()
            print(f"wechat outbox flushed: sent={flushed.sent} failed={flushed.failed}")
            for alert in format_trade_alerts(result, args.end_date):
                ok = sender.send_or_queue(alert, kind="trade")
                print(f"wechat trade alert {'sent' if ok else 'queued'}")
            ok = sender.send_or_queue(format_wechat_summary(result), kind="summary")
            print(f"wechat summary {'sent' if ok else 'queued'}")
        return 0
    if args.command == "optimize":
        result = optimize_strategy(
            bars,
            start_date=args.start_date,
            end_date=args.end_date,
            initial_cash=args.initial_cash,
        )
        save_optimization_outputs(result, Path(args.output_dir))
        if result.best is not None:
            print(format_wechat_summary(result.best))
        return 0
    if args.command == "daily-summary":
        result = run_backtest(
            bars,
            BacktestConfig(start_date=args.start_date, end_date=args.end_date),
        )
        save_backtest_outputs(result, Path(args.output_dir))
        message = format_wechat_summary(result)
        print(message)
        sender = ReliableWeChatSender(
            cc_connect=Path(args.cc_connect),
            project=args.wechat_project,
            session=args.wechat_session,
            outbox_dir=Path(args.wechat_outbox),
        )
        flushed = sender.flush_outbox()
        print(f"wechat outbox flushed: sent={flushed.sent} failed={flushed.failed}")
        for alert in format_trade_alerts(result, args.end_date):
            ok = sender.send_or_queue(alert, kind="trade")
            print(f"wechat trade alert {'sent' if ok else 'queued'}")
        ok = sender.send_or_queue(message, kind="summary")
        print(f"wechat summary {'sent' if ok else 'queued'}")
        return 0
    raise ValueError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())

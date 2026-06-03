from __future__ import annotations

import argparse
from pathlib import Path

from .backtest import BacktestConfig, run_backtest
from .factors import load_market_csv
from .history import default_history_end, load_or_fetch_histories
from .notifier import ReliableWeChatSender
from .operators import evolve_operators, save_operator_evolution
from .optimizer import optimize_strategy
from .realtime import DEFAULT_REALTIME_CODES, SinaQuoteProvider, run_realtime_monitor
from .recommendation import recommend_one_stock
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

    evolve = sub.add_parser("evolve-operators", help="evaluate and evolve technical indicator operators")
    evolve.add_argument("--csv", required=True)
    evolve.add_argument("--as-of", required=True)
    evolve.add_argument("--horizon", type=int, default=5)
    evolve.add_argument("--top-n", type=int, default=5)
    evolve.add_argument("--output-dir", default="output/stock_ai/operators")

    daily = sub.add_parser("daily-summary", help="run backtest through today and send a WeChat summary")
    daily.add_argument("--csv", required=True)
    daily.add_argument("--start-date", required=True)
    daily.add_argument("--end-date", required=True)
    daily.add_argument("--output-dir", default="output/stock_ai/daily")
    daily.add_argument("--cc-connect", default="/Users/lan/.nvm/versions/node/v23.7.0/bin/cc-connect")
    daily.add_argument("--wechat-project", default="daily-market-news")
    daily.add_argument("--wechat-session", default="weixin:dm:o9cq808Zm6pkjw0mJxDT8kaN4pKo@im.wechat")
    daily.add_argument("--wechat-outbox", default="output/stock_ai/wechat_outbox")

    realtime = sub.add_parser("realtime-monitor", help="monitor fixed stocks every second during A-share market hours")
    realtime.add_argument("--codes", default=",".join(DEFAULT_REALTIME_CODES))
    realtime.add_argument("--poll-seconds", type=float, default=1.0)
    realtime.add_argument("--cc-connect", default="/usr/local/bin/cc-connect")
    realtime.add_argument("--wechat-project", default="daily-market-news")
    realtime.add_argument("--wechat-session", default="weixin:dm:o9cq808Zm6pkjw0mJxDT8kaN4pKo@im.wechat")
    realtime.add_argument("--wechat-outbox", default="output/stock_ai/wechat_outbox")
    realtime.add_argument("--state-log", default="output/stock_ai/realtime_monitor.log")

    rec = sub.add_parser("recommend-daily", help="recommend one stock at 08:50 and send it to WeChat")
    rec.add_argument("--csv", required=True)
    rec.add_argument("--as-of", required=True)
    rec.add_argument("--codes", default=",".join(DEFAULT_REALTIME_CODES))
    rec.add_argument("--history-start", default="2025-01-01")
    rec.add_argument("--history-cache-dir", default="data/cache")
    rec.add_argument("--output-dir", default="output/stock_ai/recommendation")
    rec.add_argument("--operator-weights", default="output/stock_ai/operators/operator_weights.json")
    rec.add_argument("--cc-connect", default="/usr/local/bin/cc-connect")
    rec.add_argument("--wechat-project", default="daily-market-news")
    rec.add_argument("--wechat-session", default="weixin:dm:o9cq808Zm6pkjw0mJxDT8kaN4pKo@im.wechat")
    rec.add_argument("--wechat-outbox", default="output/stock_ai/wechat_outbox")

    flush = sub.add_parser("flush-wechat-outbox", help="retry queued WeChat messages")
    flush.add_argument("--cc-connect", default="/usr/local/bin/cc-connect")
    flush.add_argument("--wechat-project", default="daily-market-news")
    flush.add_argument("--wechat-session", default="weixin:dm:o9cq808Zm6pkjw0mJxDT8kaN4pKo@im.wechat")
    flush.add_argument("--wechat-outbox", default="output/stock_ai/wechat_outbox")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "screen":
        bars = load_market_csv(args.csv)
        candidates = select_candidates(bars, args.as_of, StrategyConfig(args.top_n, args.min_score))
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        candidates.to_csv(output, index=False)
        print(f"saved {len(candidates)} candidates to {output}")
        return 0
    if args.command == "backtest":
        bars = load_market_csv(args.csv)
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
        bars = load_market_csv(args.csv)
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
    if args.command == "evolve-operators":
        bars = load_market_csv(args.csv)
        result = evolve_operators(bars, as_of=args.as_of, horizon=args.horizon, top_n=args.top_n)
        saved = save_operator_evolution(result, Path(args.output_dir))
        print(f"saved operator weights to {saved['weights']}")
        print(f"saved operator scores to {saved['scores']}")
        for score in result.scores:
            print(
                f"{score.name}: weight={score.weight:.4f} ic={score.ic:.4f} "
                f"top_return={score.top_quantile_return:.4f} hit_rate={score.hit_rate:.2f}"
            )
        return 0
    if args.command == "daily-summary":
        bars = load_market_csv(args.csv)
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
    if args.command == "realtime-monitor":
        sender = ReliableWeChatSender(
            cc_connect=Path(args.cc_connect),
            project=args.wechat_project,
            session=args.wechat_session,
            outbox_dir=Path(args.wechat_outbox),
        )
        codes = [code.strip().zfill(6) for code in args.codes.split(",") if code.strip()]
        run_realtime_monitor(
            codes=codes,
            provider=SinaQuoteProvider(),
            sender=sender,
            poll_seconds=args.poll_seconds,
            state_log=Path(args.state_log),
        )
        return 0
    if args.command == "recommend-daily":
        bars = load_market_csv(args.csv)
        codes = [code.strip().zfill(6) for code in args.codes.split(",") if code.strip()]
        fixed_bars = bars[bars["code"].astype(str).str.zfill(6).isin(codes)]
        if fixed_bars.empty:
            fixed_bars = load_or_fetch_histories(
                codes,
                start_date=args.history_start,
                end_date=args.as_of if args.as_of else default_history_end(),
                cache_dir=Path(args.history_cache_dir),
            )
        rec = recommend_one_stock(fixed_bars, codes, as_of=args.as_of, operator_weights_path=args.operator_weights)
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"recommendation_{args.as_of}.txt").write_text(rec.message, encoding="utf-8")
        print(rec.message)
        sender = ReliableWeChatSender(
            cc_connect=Path(args.cc_connect),
            project=args.wechat_project,
            session=args.wechat_session,
            outbox_dir=Path(args.wechat_outbox),
        )
        flushed = sender.flush_outbox()
        print(f"wechat outbox flushed: sent={flushed.sent} failed={flushed.failed}")
        ok = sender.send_or_queue(rec.message, kind="recommendation")
        print(f"wechat recommendation {'sent' if ok else 'queued'}")
        return 0
    if args.command == "flush-wechat-outbox":
        sender = ReliableWeChatSender(
            cc_connect=Path(args.cc_connect),
            project=args.wechat_project,
            session=args.wechat_session,
            outbox_dir=Path(args.wechat_outbox),
        )
        flushed = sender.flush_outbox()
        print(f"wechat outbox flushed: sent={flushed.sent} failed={flushed.failed}")
        return 0
    raise ValueError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())

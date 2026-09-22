'use client';

import React, { useState } from 'react';
import top100Data from '../data/top100Momentum.json';
import { Flame, ShieldCheck, ArrowUpDown, Filter, Sparkles } from 'lucide-react';

export const TopMomentumScreener: React.FC = () => {
  const [viewLimit, setViewLimit] = useState<10 | 20 | 50 | 100>(50);
  const [sortBy, setSortBy] = useState<'sharpe3m' | 'return3m' | 'return6m' | 'return12m' | 'marketCap'>('sharpe3m');
  const [qualityOnly, setQualityOnly] = useState<boolean>(true);
  const [above200SmaOnly, setAbove200SmaOnly] = useState<boolean>(true);

  let filtered = top100Data.filter((s) => {
    if (qualityOnly && !s.isQuality) return false;
    if (above200SmaOnly && !s.above200Sma) return false;
    return true;
  });

  filtered.sort((a, b) => {
    return (b[sortBy] as number) - (a[sortBy] as number);
  });

  const displayedStocks = filtered.slice(0, viewLimit);

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 shadow-xl mb-8">
      {/* Title */}
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 mb-6 pb-4 border-b border-slate-800">
        <div>
          <h2 className="text-white font-bold text-base flex items-center gap-2">
            <Flame className="w-5 h-5 text-amber-400 animate-pulse" />
            Top NSE Momentum Stocks Screener (Live Leaderboard)
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Real-time ranked momentum leaderboard across Indian Equities (Market Cap &ge; ₹500 Cr)
          </p>
        </div>

        {/* View Limit Selector */}
        <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs font-semibold">
          <span className="text-slate-400 px-2 text-[11px]">View:</span>
          {[10, 20, 50, 100].map((limit) => (
            <button
              key={limit}
              onClick={() => setViewLimit(limit as any)}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                viewLimit === limit
                  ? 'bg-amber-500 text-slate-950 font-bold shadow-md'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Top {limit}
            </button>
          ))}
        </div>
      </div>

      {/* Filter Controls */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6 bg-slate-950 p-4 rounded-xl border border-slate-800 text-xs">
        <div>
          <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
            Sort Leaderboard By
          </label>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as any)}
            className="w-full bg-slate-900 border border-slate-800 text-white font-semibold rounded-lg px-3 py-2 focus:outline-none focus:border-amber-500"
          >
            <option value="sharpe3m">Sharpe 3M (Risk-Adjusted Momentum)</option>
            <option value="return3m">3-Month Price Return (%)</option>
            <option value="return6m">6-Month Price Return (%)</option>
            <option value="return12m">12-Month Price Return (%)</option>
            <option value="marketCap">Market Cap (₹ Cr)</option>
          </select>
        </div>

        <div className="flex items-center gap-3 self-end py-2">
          <label className="flex items-center gap-2 cursor-pointer text-slate-300">
            <input
              type="checkbox"
              checked={qualityOnly}
              onChange={(e) => setQualityOnly(e.target.checked)}
              className="accent-emerald-500 rounded w-4 h-4"
            />
            <span>Quality Screen (Net Income &gt; 0, D/E &le; 1.5)</span>
          </label>
        </div>

        <div className="flex items-center gap-3 self-end py-2">
          <label className="flex items-center gap-2 cursor-pointer text-slate-300">
            <input
              type="checkbox"
              checked={above200SmaOnly}
              onChange={(e) => setAbove200SmaOnly(e.target.checked)}
              className="accent-cyan-500 rounded w-4 h-4"
            />
            <span>Trend Shield (Price &gt; 200 SMA)</span>
          </label>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="text-slate-400 border-b border-slate-800 uppercase tracking-wider font-semibold">
              <th className="pb-3 px-3">Rank</th>
              <th className="pb-3 px-3">Symbol</th>
              <th className="pb-3 px-3 text-right">Market Cap (₹ Cr)</th>
              <th className="pb-3 px-3 text-right">Current Price</th>
              <th className="pb-3 px-3 text-right">3M Return</th>
              <th className="pb-3 px-3 text-right">6M Return</th>
              <th className="pb-3 px-3 text-right">12M Return</th>
              <th className="pb-3 px-3 text-right">200 SMA Level</th>
              <th className="pb-3 px-3 text-center">Quality & Trend Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-medium">
            {displayedStocks.map((s, idx) => (
              <tr key={s.symbol} className="hover:bg-slate-800/40 transition-all">
                <td className="py-3 px-3 text-amber-400 font-bold">#{idx + 1}</td>
                <td className="py-3 px-3 font-bold text-white">{s.symbol}</td>
                <td className="py-3 px-3 text-right text-slate-300">₹{s.marketCap.toLocaleString()} Cr</td>
                <td className="py-3 px-3 text-right font-black text-white">₹{s.currentPrice.toLocaleString()}</td>
                <td className="py-3 px-3 text-right font-bold text-emerald-400">+{s.return3m}%</td>
                <td className="py-3 px-3 text-right font-bold text-cyan-400">+{s.return6m}%</td>
                <td className="py-3 px-3 text-right font-bold text-purple-400">+{s.return12m}%</td>
                <td className="py-3 px-3 text-right text-amber-400 font-mono">₹{s.sma200.toLocaleString()}</td>
                <td className="py-3 px-3 text-center space-x-1">
                  {s.isQuality && (
                    <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 text-[10px] font-bold">
                      QUALITY
                    </span>
                  )}
                  {s.above200Sma && (
                    <span className="px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 text-[10px] font-bold">
                      &gt; 200 SMA
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

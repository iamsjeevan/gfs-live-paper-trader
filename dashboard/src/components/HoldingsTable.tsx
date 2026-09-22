import React from 'react';
import { StockHolding } from '../data/strategyData';
import { ShieldCheck, TrendingUp, AlertTriangle } from 'lucide-react';

interface HoldingsTableProps {
  holdings: StockHolding[];
  market: 'INDIA' | 'US';
}

export const HoldingsTable: React.FC<HoldingsTableProps> = ({ holdings, market }) => {
  const currencySymbol = market === 'INDIA' ? '₹' : '$';

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 shadow-xl mb-8">
      <div className="flex items-center justify-between mb-6 pb-4 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-5 h-5 text-emerald-400" />
          <h2 className="text-white font-bold text-base">Current Portfolio Holdings & Stop-Loss Monitor</h2>
        </div>
        <span className="text-xs text-slate-400">
          Rebalance Frequency: <strong className="text-emerald-400">Monthly</strong> | Integer Share Execution
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="text-slate-400 border-b border-slate-800 uppercase tracking-wider font-semibold">
              <th className="pb-3 px-3">Rank</th>
              <th className="pb-3 px-3">Symbol / Company</th>
              <th className="pb-3 px-3 text-right">Entry Price</th>
              <th className="pb-3 px-3 text-right">Current Price</th>
              <th className="pb-3 px-3 text-right">Stop Loss (200 SMA)</th>
              <th className="pb-3 px-3 text-right">Gain / Loss</th>
              <th className="pb-3 px-3 text-right">Position Value</th>
              <th className="pb-3 px-3 text-center">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-medium">
            {holdings.map((stock) => {
              const isProfit = stock.returnPct >= 0;
              return (
                <tr key={stock.symbol} className="hover:bg-slate-800/40 transition-all">
                  <td className="py-3 px-3 text-slate-400 font-bold">#{stock.momentumRank}</td>
                  <td className="py-3 px-3">
                    <div className="font-bold text-white">{stock.symbol}</div>
                    <div className="text-[10px] text-slate-400">{stock.name}</div>
                  </td>
                  <td className="py-3 px-3 text-right text-slate-300">
                    {currencySymbol}{stock.entryPrice.toLocaleString()}
                  </td>
                  <td className="py-3 px-3 text-right font-bold text-white">
                    {currencySymbol}{stock.currentPrice.toLocaleString()}
                  </td>
                  <td className="py-3 px-3 text-right text-amber-400 font-mono">
                    {currencySymbol}{stock.stopLossPrice.toLocaleString()}
                  </td>
                  <td className="py-3 px-3 text-right font-bold">
                    <span
                      className={`px-2 py-1 rounded-md text-[11px] ${
                        isProfit
                          ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                          : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                      }`}
                    >
                      {isProfit ? '+' : ''}{stock.returnPct.toFixed(2)}%
                    </span>
                  </td>
                  <td className="py-3 px-3 text-right font-black text-white">
                    {currencySymbol}{stock.positionValue.toLocaleString()}
                  </td>
                  <td className="py-3 px-3 text-center">
                    {stock.status === 'WINNER' ? (
                      <span className="px-2 py-0.5 rounded-full bg-emerald-400/10 text-emerald-400 border border-emerald-400/30 text-[10px] font-bold">
                        🏆 WINNER
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full bg-cyan-400/10 text-cyan-400 border border-cyan-400/30 text-[10px] font-bold">
                        HOLDING
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

import React from 'react';
import { DollarSign, TrendingUp, ShieldAlert, Award, PiggyBank, Percent } from 'lucide-react';

interface MetricCardsProps {
  market: 'INDIA' | 'US';
  nav: number;
  invested: number;
  cagr: number;
  maxDrawdown: number;
  winRate: number;
  leverage: number;
  yearlyCost: number;
}

export const MetricCards: React.FC<MetricCardsProps> = ({
  market,
  nav,
  invested,
  cagr,
  maxDrawdown,
  winRate,
  leverage,
  yearlyCost
}) => {
  const currencySymbol = market === 'INDIA' ? '₹' : '$';
  const formatCurrency = (val: number) => {
    if (market === 'INDIA') {
      if (val >= 10000000) return `₹${(val / 10000000).toFixed(2)} Cr`;
      if (val >= 100000) return `₹${(val / 100000).toFixed(2)} Lakhs`;
      return `₹${val.toLocaleString()}`;
    }
    if (val >= 1000000) return `$${(val / 1000000).toFixed(2)}M`;
    return `$${val.toLocaleString()}`;
  };

  const netProfit = nav - invested;
  const totalReturnPct = ((nav - invested) / invested) * 100;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* Portfolio NAV */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl relative overflow-hidden group hover:border-emerald-500/40 transition-all">
        <div className="absolute top-0 right-0 w-24 h-24 bg-emerald-500/5 rounded-full blur-2xl group-hover:bg-emerald-500/10 transition-all" />
        <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
          <span>Portfolio NAV (Today)</span>
          <span className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400">
            <DollarSign className="w-4 h-4" />
          </span>
        </div>
        <div className="text-2xl font-black text-white tracking-tight">
          {formatCurrency(nav)}
        </div>
        <div className="flex items-center gap-2 mt-2 text-xs">
          <span className="text-emerald-400 font-bold flex items-center gap-0.5">
            +{totalReturnPct.toFixed(1)}% Total
          </span>
          <span className="text-slate-500">| Profit: {formatCurrency(netProfit)}</span>
        </div>
      </div>

      {/* Compound Annual Growth Rate (CAGR) */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl relative overflow-hidden group hover:border-cyan-500/40 transition-all">
        <div className="absolute top-0 right-0 w-24 h-24 bg-cyan-500/5 rounded-full blur-2xl group-hover:bg-cyan-500/10 transition-all" />
        <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
          <span>Strategy CAGR</span>
          <span className="p-1.5 rounded-lg bg-cyan-500/10 text-cyan-400">
            <TrendingUp className="w-4 h-4" />
          </span>
        </div>
        <div className="text-2xl font-black text-cyan-400 tracking-tight">
          {cagr.toFixed(2)}% / year
        </div>
        <div className="flex items-center gap-2 mt-2 text-xs text-slate-400">
          <span>3-Tier Dynamic ({leverage}x MTF)</span>
          <span className="text-cyan-400 font-semibold">Verified</span>
        </div>
      </div>

      {/* Maximum Historical Drawdown */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl relative overflow-hidden group hover:border-amber-500/40 transition-all">
        <div className="absolute top-0 right-0 w-24 h-24 bg-amber-500/5 rounded-full blur-2xl group-hover:bg-amber-500/10 transition-all" />
        <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
          <span>Max Crash Drawdown</span>
          <span className="p-1.5 rounded-lg bg-amber-500/10 text-amber-400">
            <ShieldAlert className="w-4 h-4" />
          </span>
        </div>
        <div className="text-2xl font-black text-amber-400 tracking-tight">
          {maxDrawdown.toFixed(2)}%
        </div>
        <div className="flex items-center gap-2 mt-2 text-xs text-slate-400">
          <span>Win Rate: <strong className="text-emerald-400">{winRate}%</strong></span>
          <span className="text-slate-500">| 200 SMA Shield</span>
        </div>
      </div>

      {/* Arbitrage Cash & MTF Cost Drag */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl relative overflow-hidden group hover:border-purple-500/40 transition-all">
        <div className="absolute top-0 right-0 w-24 h-24 bg-purple-500/5 rounded-full blur-2xl group-hover:bg-purple-500/10 transition-all" />
        <div className="flex items-center justify-between text-slate-400 text-xs mb-2">
          <span>Yearly Broker Charges</span>
          <span className="p-1.5 rounded-lg bg-purple-500/10 text-purple-400">
            <PiggyBank className="w-4 h-4" />
          </span>
        </div>
        <div className="text-2xl font-black text-purple-300 tracking-tight">
          {formatCurrency(yearlyCost)}
        </div>
        <div className="flex items-center gap-2 mt-2 text-xs text-slate-400">
          <span>Idle Cash Yield: <strong className="text-emerald-400">7.0% P.A.</strong></span>
        </div>
      </div>
    </div>
  );
};

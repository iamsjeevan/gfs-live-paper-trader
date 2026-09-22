import React from 'react';
import { Sliders, CheckCircle2, Shield, Zap } from 'lucide-react';

interface ControlsProps {
  numStocks: 10 | 20;
  setNumStocks: (n: 10 | 20) => void;
  leverageMode: '1.0' | '1.25' | '1.5' | '3TIER';
  setLeverageMode: (l: '1.0' | '1.25' | '1.5' | '3TIER') => void;
  trendFilter: '200SMA' | '50SMA' | 'NONE';
  setTrendFilter: (t: '200SMA' | '50SMA' | 'NONE') => void;
  momFormula: 'SHARPE_3M' | 'VOL_ADJ_6M' | 'M12_1M';
  setMomFormula: (m: 'SHARPE_3M' | 'VOL_ADJ_6M' | 'M12_1M') => void;
}

export const StrategyControls: React.FC<ControlsProps> = ({
  numStocks,
  setNumStocks,
  leverageMode,
  setLeverageMode,
  trendFilter,
  setTrendFilter,
  momFormula,
  setMomFormula,
}) => {
  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 shadow-xl mb-8">
      <div className="flex items-center gap-2 mb-6 text-white font-bold text-base border-b border-slate-800 pb-3">
        <Sliders className="w-5 h-5 text-emerald-400" />
        <h2>Interactive Strategy Simulator Controls</h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {/* 1. Portfolio Size (10 vs 20 Stocks) */}
        <div>
          <label className="block text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wider">
            Portfolio Allocation Size
          </label>
          <div className="grid grid-cols-2 gap-2 bg-slate-950 p-1 rounded-xl border border-slate-800">
            <button
              onClick={() => setNumStocks(10)}
              className={`py-2 text-xs font-bold rounded-lg transition-all ${
                numStocks === 10
                  ? 'bg-emerald-500 text-slate-950 shadow-md'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              10 Stocks
            </button>
            <button
              onClick={() => setNumStocks(20)}
              className={`py-2 text-xs font-bold rounded-lg transition-all ${
                numStocks === 20
                  ? 'bg-emerald-500 text-slate-950 shadow-md'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              20 Stocks
            </button>
          </div>
        </div>

        {/* 2. Leverage Matrix Selector */}
        <div>
          <label className="block text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wider">
            Leverage Strategy Mode
          </label>
          <select
            value={leverageMode}
            onChange={(e) => setLeverageMode(e.target.value as any)}
            className="w-full bg-slate-950 border border-slate-800 text-white text-xs font-semibold rounded-xl px-3 py-2.5 focus:outline-none focus:border-emerald-500"
          >
            <option value="3TIER">🏆 3-Tier Dynamic Matrix (1.5x Bull / 1.25x Dip / 1.0x Bear)</option>
            <option value="1.0">1.0x Cash Only (No Leverage)</option>
            <option value="1.25">1.25x Moderate MTF Leverage (25% Margin)</option>
            <option value="1.5">1.5x Aggressive MTF Leverage (50% Margin)</option>
          </select>
        </div>

        {/* 3. Moving Average Trend Filter */}
        <div>
          <label className="block text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wider">
            Trend Protection Filter
          </label>
          <div className="grid grid-cols-3 gap-1 bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs">
            <button
              onClick={() => setTrendFilter('200SMA')}
              className={`py-2 font-bold rounded-lg transition-all ${
                trendFilter === '200SMA'
                  ? 'bg-cyan-500 text-slate-950 shadow-md'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              200 SMA
            </button>
            <button
              onClick={() => setTrendFilter('50SMA')}
              className={`py-2 font-bold rounded-lg transition-all ${
                trendFilter === '50SMA'
                  ? 'bg-cyan-500 text-slate-950 shadow-md'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              50 SMA
            </button>
            <button
              onClick={() => setTrendFilter('NONE')}
              className={`py-2 font-bold rounded-lg transition-all ${
                trendFilter === 'NONE'
                  ? 'bg-amber-500 text-slate-950 shadow-md'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              None
            </button>
          </div>
        </div>

        {/* 4. Momentum Ranking Formula */}
        <div>
          <label className="block text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wider">
            Momentum Formula
          </label>
          <select
            value={momFormula}
            onChange={(e) => setMomFormula(e.target.value as any)}
            className="w-full bg-slate-950 border border-slate-800 text-white text-xs font-semibold rounded-xl px-3 py-2.5 focus:outline-none focus:border-emerald-500"
          >
            <option value="SHARPE_3M">Sharpe 3M (Risk-Adjusted 3M Momentum)</option>
            <option value="VOL_ADJ_6M">Vol-Adjusted (6M - 1M) Momentum</option>
            <option value="M12_1M">Academic 12M - 1M Momentum</option>
          </select>
        </div>
      </div>
    </div>
  );
};

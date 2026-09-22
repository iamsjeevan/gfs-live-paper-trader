'use client';

import React, { useState } from 'react';
import livePortfoliosData from '../data/live10Portfolios.json';
import { TopMomentumScreener } from '../components/TopMomentumScreener';
import { ShieldCheck, Cpu, Layers, Calendar, CheckCircle2, RefreshCw, Flame, LayoutDashboard } from 'lucide-react';

export default function Home() {
  const [activeTab, setActiveTab] = useState<'PORTFOLIOS' | 'SCREENER'>('PORTFOLIOS');
  const [selectedPortfolioId, setSelectedPortfolioId] = useState<number>(1);

  const selectedPortfolio = livePortfoliosData.find((p) => p.id === selectedPortfolioId) || livePortfoliosData[0];
  const holdings = selectedPortfolio.holdings;
  const initialCapital = 100000.0;
  const currentNav = 100000.0;
  const numStocks = selectedPortfolio.numStocks;
  const targetLeverage = selectedPortfolio.targetLeverage;

  const totalPurchasingPower = initialCapital * targetLeverage;
  const totalMtfBorrowed = Math.max(totalPurchasingPower - initialCapital, 0.0);
  const dailyMtfInterest = totalMtfBorrowed * 0.0004;
  const monthlyMtfInterest = dailyMtfInterest * 30;
  const monthlyBrokerage = (numStocks * 2) * 20;
  const monthlyEstCharges = monthlyMtfInterest + monthlyBrokerage + 150;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans selection:bg-emerald-500 selection:text-slate-950">
      {/* Header */}
      <header className="bg-slate-900/90 backdrop-blur-md border-b border-slate-800 sticky top-0 z-50 px-4 lg:px-8 py-4">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-cyan-500 flex items-center justify-center shadow-lg shadow-emerald-500/20">
              <Cpu className="w-6 h-6 text-slate-950 font-bold" />
            </div>
            <div>
              <h1 className="text-xl font-extrabold text-white tracking-tight flex items-center gap-2">
                QTDL Momentum Engine <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-bold">LIVE VERCEL APP 2026</span>
              </h1>
              <p className="text-xs text-slate-400">Live 24/7 Cloud Tracker | ₹1 Lakh Initial Capital Per Portfolio</p>
            </div>
          </div>

          {/* Navigation Tabs */}
          <div className="flex items-center bg-slate-950 p-1.5 rounded-xl border border-slate-800 gap-1">
            <button
              onClick={() => setActiveTab('PORTFOLIOS')}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold transition-all ${
                activeTab === 'PORTFOLIOS'
                  ? 'bg-emerald-500 text-slate-950 shadow-md shadow-emerald-500/20'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <LayoutDashboard className="w-4 h-4" />
              10 Live Portfolios (₹1L Today)
            </button>
            <button
              onClick={() => setActiveTab('SCREENER')}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold transition-all ${
                activeTab === 'SCREENER'
                  ? 'bg-amber-500 text-slate-950 shadow-md shadow-amber-500/20'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <Flame className="w-4 h-4" />
              Top Momentum Screener (Top 100/50)
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 lg:px-8 py-8">
        {activeTab === 'SCREENER' ? (
          <TopMomentumScreener />
        ) : (
          <>
            {/* 10 Portfolio Variant Selector */}
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl mb-8">
              <div className="flex items-center gap-2 mb-4 text-xs font-bold text-slate-400 uppercase tracking-wider">
                <Layers className="w-4 h-4 text-emerald-400" />
                <span>Select Live Portfolio Variant to View (10 Distinct Trackers)</span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2">
                {livePortfoliosData.map((p) => {
                  const isSelected = p.id === selectedPortfolioId;
                  return (
                    <button
                      key={p.id}
                      onClick={() => setSelectedPortfolioId(p.id)}
                      className={`text-left p-3 rounded-xl border text-xs transition-all ${
                        isSelected
                          ? 'bg-emerald-500/10 border-emerald-500 text-white shadow-lg shadow-emerald-500/10'
                          : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700 hover:text-white'
                      }`}
                    >
                      <div className="font-bold text-white mb-1 truncate">{p.name}</div>
                      <div className="flex items-center justify-between text-[10px] text-slate-400">
                        <span>{p.numStocks} Stocks</span>
                        <span className="text-cyan-400 font-semibold">{p.targetLeverage}x Leverage</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Selected Portfolio Overview Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
              <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl">
                <div className="text-slate-400 text-xs mb-1">Starting Capital (Today)</div>
                <div className="text-2xl font-black text-white">₹1,00,000.00</div>
                <div className="text-xs text-emerald-400 font-bold mt-1">₹1 Lakh Initialized Today</div>
              </div>

              <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl">
                <div className="text-slate-400 text-xs mb-1">Current Portfolio NAV</div>
                <div className="text-2xl font-black text-emerald-400">₹{currentNav.toLocaleString()}.00</div>
                <div className="text-xs text-slate-400 mt-1">Unrealized P&L: <strong className="text-emerald-400">₹0.00 (0.0%)</strong></div>
              </div>

              <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl">
                <div className="text-slate-400 text-xs mb-1">Total Purchasing Power</div>
                <div className="text-2xl font-black text-cyan-400">₹{totalPurchasingPower.toLocaleString()}</div>
                <div className="text-xs text-slate-400 mt-1">{targetLeverage}x Target Exposure ({numStocks} Stocks)</div>
              </div>

              <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl">
                <div className="text-slate-400 text-xs mb-1">MTF Borrowed / Charges</div>
                <div className="text-2xl font-black text-purple-400">₹{monthlyEstCharges.toFixed(0)} / mo</div>
                <div className="text-xs text-slate-400 mt-1">Borrowed: ₹{totalMtfBorrowed.toLocaleString()} (₹{dailyMtfInterest.toFixed(1)}/day)</div>
              </div>
            </div>

            {/* Live Holdings Table */}
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 shadow-xl mb-8">
              <div className="flex items-center justify-between mb-6 pb-4 border-b border-slate-800">
                <div>
                  <h2 className="text-white font-bold text-base flex items-center gap-2">
                    <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                    Live Stock Positions Initialized TODAY (August 26, 2026)
                  </h2>
                  <p className="text-xs text-slate-400 mt-0.5">{selectedPortfolio.name}</p>
                </div>
                <span className="text-xs px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-bold">
                  PORTFOLIO #{selectedPortfolio.id} ACTIVE
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="text-slate-400 border-b border-slate-800 uppercase tracking-wider font-semibold">
                      <th className="pb-3 px-3">Rank</th>
                      <th className="pb-3 px-3">Symbol</th>
                      <th className="pb-3 px-3 text-right">Entry Price (Today)</th>
                      <th className="pb-3 px-3 text-right">Shares Bought</th>
                      <th className="pb-3 px-3 text-right">Position Value</th>
                      <th className="pb-3 px-3 text-right">Stop Loss (200 SMA)</th>
                      <th className="pb-3 px-3 text-right">MTF Exposure</th>
                      <th className="pb-3 px-3 text-center">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 font-medium">
                    {holdings.map((stock) => (
                      <tr key={stock.symbol} className="hover:bg-slate-800/40 transition-all">
                        <td className="py-3 px-3 text-slate-400 font-bold">#{stock.momentumRank}</td>
                        <td className="py-3 px-3 font-bold text-white">{stock.symbol}</td>
                        <td className="py-3 px-3 text-right text-slate-300">₹{stock.entryPrice.toLocaleString()}</td>
                        <td className="py-3 px-3 text-right font-black text-cyan-400">{stock.shares} shares</td>
                        <td className="py-3 px-3 text-right font-black text-white">₹{stock.positionValue.toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-amber-400 font-mono">₹{stock.stopLossPrice.toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-purple-300 font-mono">₹{stock.mtfExposure.toLocaleString()}</td>
                        <td className="py-3 px-3 text-center">
                          <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 text-[10px] font-bold">
                            BOUGHT TODAY
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </main>

      <footer className="border-t border-slate-900 bg-slate-950/80 py-6 text-center text-xs text-slate-500">
        <p>QTDL Momentum Engine &copy; 2026 | Initialized Aug 26, 2026 with Strictly ₹1,00,000 per Portfolio</p>
      </footer>
    </div>
  );
}

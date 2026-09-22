'use client';

import React from 'react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid
} from 'recharts';
import { LineChart, TrendingUp } from 'lucide-react';

interface PerformanceChartProps {
  data: Array<{ date: string; strategy: number; [key: string]: any }>;
  market: 'INDIA' | 'US';
}

export const PerformanceChart: React.FC<PerformanceChartProps> = ({ data, market }) => {
  const benchmarkKey = market === 'INDIA' ? 'nifty' : 'sp500';
  const benchmarkLabel = market === 'INDIA' ? 'Nifty 50 Index' : 'S&P 500 Index';

  const formatYAxis = (val: number) => {
    if (market === 'INDIA') {
      if (val >= 10000000) return `₹${(val / 10000000).toFixed(1)}Cr`;
      if (val >= 100000) return `₹${(val / 100000).toFixed(0)}L`;
      return `₹${val}`;
    }
    if (val >= 1000000) return `$${(val / 1000000).toFixed(1)}M`;
    if (val >= 1000) return `$${(val / 1000).toFixed(0)}k`;
    return `$${val}`;
  };

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 shadow-xl mb-8">
      <div className="flex items-center justify-between mb-6 pb-4 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-5 h-5 text-emerald-400" />
          <h2 className="text-white font-bold text-base">Historical Equity Curve vs Benchmark</h2>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-emerald-400" />
            <span className="text-slate-300 font-semibold">QTDL Strategy (3-Tier Dynamic)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-slate-600" />
            <span className="text-slate-400 font-medium">{benchmarkLabel}</span>
          </div>
        </div>
      </div>

      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 10, right: 30, left: 10, bottom: 0 }}>
            <defs>
              <linearGradient id="strategyGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#10b981" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#10b981" stopOpacity={0.0} />
              </linearGradient>
              <linearGradient id="benchGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#64748b" stopOpacity={0.2} />
                <stop offset="95%" stopColor="#64748b" stopOpacity={0.0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="date" stroke="#64748b" fontSize={11} tickLine={false} />
            <YAxis tickFormatter={formatYAxis} stroke="#64748b" fontSize={11} tickLine={false} />
            <Tooltip
              contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', borderRadius: '12px' }}
              formatter={(val: any) => [formatYAxis(Number(val)), 'Value']}
            />
            <Area type="monotone" dataKey="strategy" stroke="#10b981" strokeWidth={3} fillOpacity={1} fill="url(#strategyGrad)" />
            <Area type="monotone" dataKey={benchmarkKey} stroke="#64748b" strokeWidth={2} fillOpacity={1} fill="url(#benchGrad)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

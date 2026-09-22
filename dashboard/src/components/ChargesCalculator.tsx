import React from 'react';
import { Calculator, Receipt, ShieldCheck } from 'lucide-react';

interface ChargesProps {
  market: 'INDIA' | 'US';
  leverage: number;
}

export const ChargesCalculator: React.FC<ChargesProps> = ({ market, leverage }) => {
  const isIndia = market === 'INDIA';

  // Base charges math for ₹10L capital
  const capital = 1000000;
  const portfolioVal = capital * leverage;
  const borrowed = Math.max(portfolioVal - capital, 0);

  const mtfDailyInterestRate = 0.0004; // 0.04% / day
  const monthlyInterest = borrowed * mtfDailyInterestRate * 30;
  const yearlyInterest = monthlyInterest * 12;

  const monthlyBrokerage = 400; // 20 orders * ₹20
  const monthlyStt = (portfolioVal * 0.3 * 0.001) * 2;
  const monthlyPledgeDp = 250;
  const monthlyTradingCharges = monthlyBrokerage + monthlyStt + monthlyPledgeDp;

  const totalMonthlyCost = monthlyInterest + monthlyTradingCharges;
  const totalYearlyCost = totalMonthlyCost * 12;
  const costPctCapital = (totalYearlyCost / capital) * 100;

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 shadow-xl mb-8">
      <div className="flex items-center justify-between mb-6 pb-4 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Receipt className="w-5 h-5 text-purple-400" />
          <h2 className="text-white font-bold text-base">Real-World Brokerage & MTF Cost Calculator</h2>
        </div>
        <span className="text-xs px-2.5 py-1 rounded-full bg-purple-500/10 text-purple-300 border border-purple-500/30 font-semibold">
          Zerodha / Groww MTF Rate: 0.04% / day (14.6% P.A.)
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
          <div className="text-slate-400 text-xs mb-1">Monthly MTF Interest (0.04%/day)</div>
          <div className="text-lg font-black text-rose-400">
            {isIndia ? `₹${monthlyInterest.toLocaleString()}` : `$${(monthlyInterest / 83).toFixed(2)}`} / mo
          </div>
          <div className="text-[10px] text-slate-500 mt-1">On borrowed {isIndia ? `₹${(borrowed/100000).toFixed(1)}L` : `$${borrowed}`}</div>
        </div>

        <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
          <div className="text-slate-400 text-xs mb-1">Brokerage & Statutory Taxes</div>
          <div className="text-lg font-black text-amber-400">
            {isIndia ? `₹${monthlyTradingCharges.toLocaleString()}` : `$${(monthlyTradingCharges / 83).toFixed(2)}`} / mo
          </div>
          <div className="text-[10px] text-slate-500 mt-1">STT (0.1%), GST (18%), DP charges</div>
        </div>

        <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
          <div className="text-slate-400 text-xs mb-1">Total Yearly Charges</div>
          <div className="text-lg font-black text-purple-400">
            {isIndia ? `₹${totalYearlyCost.toLocaleString()}` : `$${(totalYearlyCost / 83).toFixed(2)}`} / yr
          </div>
          <div className="text-[10px] text-slate-500 mt-1">Combined interest + taxes</div>
        </div>

        <div className="bg-slate-950 p-4 rounded-xl border border-slate-800">
          <div className="text-slate-400 text-xs mb-1">Net Cost Drag on Capital</div>
          <div className="text-lg font-black text-emerald-400">
            {costPctCapital.toFixed(2)}% / yr
          </div>
          <div className="text-[10px] text-slate-500 mt-1">Net CAGR Drag Impact</div>
        </div>
      </div>
    </div>
  );
};

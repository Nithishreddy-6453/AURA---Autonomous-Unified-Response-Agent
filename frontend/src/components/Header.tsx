import React from "react";

interface HeaderProps {
  isConnected: boolean;
}

export const Header: React.FC<HeaderProps> = ({ isConnected }) => {
  return (
    <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="h-8 w-8 rounded bg-blue-600 flex items-center justify-center font-bold text-white tracking-widest text-sm shadow-inner">
            A
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-bold text-lg text-slate-100 tracking-wider">AURA</span>
              <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">v0.5.0</span>
            </div>
            <p className="text-xs text-slate-400">Autonomous Unified Response Agent — Operations Console</p>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <span
            className={`inline-block w-2.5 h-2.5 rounded-full ${
              isConnected ? "bg-emerald-500 animate-pulse" : "bg-rose-500"
            }`}
          />
          <span
            className={`text-xs font-mono font-medium ${
              isConnected ? "text-emerald-400" : "text-rose-400"
            }`}
          >
            {isConnected ? "API Connected" : "API Disconnected"}
          </span>
        </div>
      </div>
    </header>
  );
};

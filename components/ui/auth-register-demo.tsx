"use client";

import React, { useState, useId } from "react";
import AnimatedGradientBackground from "@/components/ui/animated-gradient-background";
import { PasswordStrength } from "@/components/ui/password-strength";

export function AuthRegisterDemo() {
  const passwordId = useId();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  return (
    <div className="relative min-h-screen w-full flex items-center justify-center overflow-hidden bg-[#0A0A0A] p-4 text-white">
      {/* Animated Breathing Radial Gradient Background */}
      <AnimatedGradientBackground
        startingGap={110}
        Breathing={true}
        animationSpeed={0.02}
        breathingRange={6}
        gradientColors={[
          "#0A0A0A",
          "#2979FF",
          "#FF80AB",
          "#FF6D00",
          "#FFD600",
          "#00E676",
          "#3D5AFE",
        ]}
        gradientStops={[35, 50, 60, 70, 80, 90, 100]}
      />

      {/* Registration Card on top of the Animated Gradient */}
      <div className="relative z-10 w-full max-w-md rounded-2xl border border-white/10 bg-white/10 p-6 md:p-8 backdrop-blur-xl shadow-2xl">
        <div className="text-center mb-6">
          <div className="inline-block text-3xl mb-2">💕</div>
          <h2 className="text-2xl font-bold tracking-tight text-white">
            Create an Account
          </h2>
          <p className="text-sm text-stone-300 mt-1">
            Sign up to connect and discover sparks in real-time.
          </p>
        </div>

        <form onSubmit={(e) => e.preventDefault()} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-stone-300 mb-1.5">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Choose your username"
              className="h-10 w-full rounded-xl border border-white/15 bg-black/30 px-3 text-sm text-white placeholder-stone-400 outline-none transition focus:border-pink-500 focus:ring-2 focus:ring-pink-500/20"
              required
            />
          </div>

          <div>
            <label
              htmlFor={passwordId}
              className="block text-xs font-semibold uppercase tracking-wider text-stone-300 mb-1.5"
            >
              Password
            </label>
            <input
              id={passwordId}
              type="password"
              value={password}
              autoComplete="new-password"
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Choose a strong password"
              className="h-10 w-full rounded-xl border border-white/15 bg-black/30 px-3 text-sm text-white placeholder-stone-400 outline-none transition focus:border-pink-500 focus:ring-2 focus:ring-pink-500/20"
              required
            />
            {/* Interactive Password Strength Indicator */}
            <PasswordStrength value={password} className="mt-3" />
          </div>

          <button
            type="submit"
            className="w-full h-11 rounded-xl bg-gradient-to-r from-pink-500 to-rose-600 font-semibold text-white shadow-lg shadow-pink-500/30 transition hover:brightness-110 active:scale-[0.99]"
          >
            Create My Account ✨
          </button>
        </form>
      </div>
    </div>
  );
}

export default AuthRegisterDemo;

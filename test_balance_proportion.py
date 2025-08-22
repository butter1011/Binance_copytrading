#!/usr/bin/env python3
"""
Test script to verify balance proportion calculation is working correctly
"""

def test_balance_ratio_calculation():
    """Test the balance ratio calculation with the user's specific example"""
    
    # User's scenario
    master_balance = 12.2  # $12.2
    follower_balance = 55.5  # $55.5
    master_quantity = 15.0  # 15 XRP
    price = 2.8  # $2.8 per XRP
    
    # Expected calculations
    balance_ratio = follower_balance / master_balance
    master_notional = master_quantity * price
    follower_notional = master_notional * balance_ratio
    expected_follower_quantity = follower_notional / price
    
    print("🧮 Balance Proportion Calculation Test")
    print("=" * 50)
    print(f"Master balance: ${master_balance}")
    print(f"Follower balance: ${follower_balance}")
    print(f"Balance ratio: {balance_ratio:.4f} (follower has {balance_ratio:.2f}x more money)")
    print()
    
    print(f"Master trade: {master_quantity} XRP @ ${price} = ${master_notional}")
    print(f"Expected follower trade: {expected_follower_quantity:.2f} XRP @ ${price} = ${follower_notional:.2f}")
    print()
    
    # Risk assessment
    master_risk_percentage = (master_notional / master_balance) * 100
    follower_risk_percentage = (follower_notional / follower_balance) * 100
    
    print(f"Master risk: {master_risk_percentage:.1f}% of balance")
    print(f"Follower risk: {follower_risk_percentage:.1f}% of balance")
    print(f"Risk ratio: {follower_risk_percentage / master_risk_percentage:.2f}x (should be close to 1.0 for proportional risk)")
    print()
    
    # Safety limits check
    max_risk_percentage = 50.0  # New default
    is_within_safety_limits = follower_risk_percentage <= max_risk_percentage
    
    print("🛡️ Safety Limits Assessment")
    print("-" * 30)
    print(f"Max allowed risk: {max_risk_percentage}%")
    print(f"Calculated risk: {follower_risk_percentage:.1f}%")
    print(f"Within limits: {'✅ YES' if is_within_safety_limits else '❌ NO'}")
    
    if not is_within_safety_limits:
        # Calculate reduced quantity
        max_risk_value = follower_balance * (max_risk_percentage / 100.0)
        safe_quantity = max_risk_value / price
        print(f"Would be reduced to: {safe_quantity:.2f} XRP (${max_risk_value:.2f} value)")
    
    print()
    print("📊 Summary")
    print("-" * 20)
    print(f"User reported getting: 1.8 XRP (this was with 10% safety limit)")
    print(f"With 50% safety limit: {expected_follower_quantity:.2f} XRP")
    print(f"Perfect proportional: {expected_follower_quantity:.2f} XRP")
    
    # Test multiple orders
    print()
    print("🔄 Testing Multiple Orders")
    print("-" * 30)
    master_orders = [15.0, 10.0, 5.0]  # User's example
    
    for i, qty in enumerate(master_orders):
        notional = qty * price
        follower_qty = (notional * balance_ratio) / price
        risk_pct = (follower_qty * price / follower_balance) * 100
        
        safe_qty = follower_qty if risk_pct <= max_risk_percentage else (follower_balance * max_risk_percentage / 100.0) / price
        
        print(f"Order {i+1}: {qty} XRP → {safe_qty:.2f} XRP (risk: {min(risk_pct, max_risk_percentage):.1f}%)")

if __name__ == "__main__":
    test_balance_ratio_calculation()

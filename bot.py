from datetime import datetime
import time

import pandas as pd
from binance.client import Client
from ta.momentum import RSIIndicator

client = Client()

symbol = "BTCUSDT"
interval = Client.KLINE_INTERVAL_1MINUTE
limit = 120

saldo_inicial = 1000.0
saldo_usdt = saldo_inicial
btc = 0.0
posicao = None
preco_entrada = 0.0
maior_preco_posicao = 0.0

log_file = "log_operacoes.txt"

# Controle de frequência para evitar overtrading
cooldown_loops = 3
loops_desde_saida = cooldown_loops

# Parâmetros da estratégia
min_diferenca_medias = 12.0
rsi_compra_min = 53.0
rsi_compra_max = 67.0
rsi_reversao_max = 30.0
rsi_saida_alto = 74.0

stop_loss_pct = 0.006      # 0,6%
take_profit_pct = 0.010    # 1,0%
trailing_stop_pct = 0.004  # 0,4%


def registrar_log(mensagem: str) -> None:
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{agora}] {mensagem}"
    print(linha)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(linha + "\n")


def get_data() -> pd.DataFrame:
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)

    df = pd.DataFrame(klines, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    return df


def fechar_posicao(tipo_saida: str, price: float) -> None:
    global saldo_usdt, btc, posicao, preco_entrada, loops_desde_saida, maior_preco_posicao

    saldo_usdt = btc * price
    lucro = saldo_usdt - saldo_inicial

    btc = 0.0
    posicao = None
    preco_entrada = 0.0
    maior_preco_posicao = 0.0
    loops_desde_saida = 0

    registrar_log(
        f">>> {tipo_saida} em {price:.2f} | Resultado acumulado: {lucro:.2f} USDT | Patrimônio: {saldo_usdt:.2f} USDT"
    )


while True:
    try:
        df = get_data()

        df["ma_fast"] = df["close"].rolling(window=9).mean()
        df["ma_slow"] = df["close"].rolling(window=21).mean()
        df["rsi"] = RSIIndicator(close=df["close"], window=14).rsi()

        # Candle atual e anterior
        price = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        open_price = df["open"].iloc[-1]

        ma_fast = df["ma_fast"].iloc[-1]
        ma_slow = df["ma_slow"].iloc[-1]
        prev_ma_fast = df["ma_fast"].iloc[-2]
        prev_ma_slow = df["ma_slow"].iloc[-2]

        rsi = df["rsi"].iloc[-1]

        if pd.isna(ma_fast) or pd.isna(ma_slow) or pd.isna(prev_ma_fast) or pd.isna(prev_ma_slow) or pd.isna(rsi):
            print("Aguardando dados suficientes...")
            time.sleep(10)
            continue

        diferenca_medias = ma_fast - ma_slow
        candle_alta = price > open_price
        candle_anterior_alta = prev_close > df["open"].iloc[-2]

        tendencia_alta = ma_fast > ma_slow and prev_ma_fast > prev_ma_slow
        tendencia_baixa = ma_fast < ma_slow and prev_ma_fast < prev_ma_slow

        sinal = "NEUTRO"
        motivo_compra = ""

        # Compra por tendência confirmada
        if (
            loops_desde_saida >= cooldown_loops
            and posicao is None
            and tendencia_alta
            and diferenca_medias >= min_diferenca_medias
            and rsi_compra_min <= rsi <= rsi_compra_max
            and candle_alta
            and candle_anterior_alta
        ):
            sinal = "COMPRA"
            motivo_compra = "tendência forte confirmada"

        # Compra por reversão mais seletiva
        elif (
            loops_desde_saida >= cooldown_loops
            and posicao is None
            and tendencia_baixa
            and diferenca_medias <= -min_diferenca_medias
            and rsi <= rsi_reversao_max
            and candle_alta
        ):
            sinal = "COMPRA"
            motivo_compra = "reversão forte seletiva"

        if sinal == "COMPRA" and posicao is None:
            btc = saldo_usdt / price
            preco_entrada = price
            maior_preco_posicao = price
            saldo_usdt = 0.0
            posicao = "COMPRADO"

            patrimonio = btc * price
            registrar_log(
                f">>> COMPRA SIMULADA em {price:.2f} | Motivo: {motivo_compra} | Patrimônio: {patrimonio:.2f} USDT"
            )

        elif posicao == "COMPRADO":
            maior_preco_posicao = max(maior_preco_posicao, price)

            # 1. Stop loss fixo
            if price <= preco_entrada * (1 - stop_loss_pct):
                fechar_posicao("STOP LOSS", price)

            # 2. Take profit
            elif price >= preco_entrada * (1 + take_profit_pct):
                fechar_posicao("TAKE PROFIT", price)

            # 3. Saída por RSI muito alto
            elif rsi >= rsi_saida_alto:
                fechar_posicao("VENDA RSI ALTO", price)

            # 4. Trailing stop para proteger lucro
            elif (
                maior_preco_posicao > preco_entrada * 1.004
                and price <= maior_preco_posicao * (1 - trailing_stop_pct)
            ):
                fechar_posicao("TRAILING STOP", price)

            # 5. Saída por perda clara de força
            elif tendencia_baixa and diferenca_medias <= -8 and rsi >= 35:
                fechar_posicao("VENDA POR SINAL", price)

        patrimonio = saldo_usdt if posicao is None else btc * price

        print(
            f"Preço: {price:.2f} | "
            f"MA9: {ma_fast:.2f} | "
            f"MA21: {ma_slow:.2f} | "
            f"RSI: {rsi:.2f} | "
            f"ΔMédias: {diferenca_medias:.2f}"
        )
        print(
            f"Sinal: {sinal} | "
            f"Posição: {posicao} | "
            f"Patrimônio: {patrimonio:.2f} USDT | "
            f"Loops pós-saída: {loops_desde_saida}"
        )
        print("-" * 70)

        if posicao is None and loops_desde_saida < cooldown_loops:
            loops_desde_saida += 1

        time.sleep(10)

    except Exception as e:
        registrar_log(f"Erro: {e}")
        time.sleep(5)
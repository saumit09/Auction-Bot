Every round, the bot participates in a simultaneous auction where it must analyze its private information, manage its bankroll, and submit a bid to maximize long-term profit. To play the game effectively, the bot's logic must handle a continuous stream of data, adapt to sudden hidden market changes, and respect strict capital limits.

The Core Bidding Loop
The game consists of 2000 continuous rounds.
At the start of each round, the bot is fed specific state variables: its private value for that round ($x_i$), its current capital, the number of active players, the round index, the top two bids from the previous round, and its own performance (bid, rank, payoff) from the previous round.
Using this data and any continuous internal state it chooses to save, the bot calculates and submits a fractional bid.
The bot's bid must lie between 0 and its current capital. If the bot submits an illegal bid (negative, NaN, exceeding capital) or takes more than 1 second to execute, the system forcefully sets its bid to 0 for that round.
After the round resolves, the bot's capital is updated by adding its earned payoff.

Navigating Hidden Blocks
The 2000 rounds are secretly divided into 4 blocks of 500 rounds.
At the start of each block, the system secretly draws a new minimum value ($m_b$) and range ($R_b$), meaning the distribution of the bot's incoming private values fundamentally changes.
The bot is never notified that a block has changed or what the new distribution parameters are. A core part of the bot's programmed logic must be detecting these regime changes purely from observing the incoming data.
At each hidden block boundary, the bot is assigned a newly randomized starting capital. Because capital does not carry over between blocks, the bot must assess whether it is starting the new block rich or poor and adjust its bidding aggression accordingly.
If the bot's capital drops to zero, it goes bankrupt and is frozen out of the game until the next block boundary resets the market and provides a fresh capital draw.

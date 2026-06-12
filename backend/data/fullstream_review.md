# Full-stream review sheet

**Review performed by Claude (AI), 2026-06-11, from +/-4 lines of context per fire.**
**Result: 3 real, 5 ambiguous, 92 false alarms out of 100 sampled fires.** `[x]` = real, `[~]` = ambiguous.


A seeded random sample of 20 action predictions ("fires") per
transcript, drawn from all fires of the TF-IDF logistic regression on
UNLABELLED lines of the five held-out test transcripts. For each entry, tick
the checkbox if the trader really performed a trade action at that moment
(any action, even if the predicted type is wrong); leave it unticked if it
is a false alarm. The ticked fraction estimates full-stream precision.

## 2025-10-07__LIVE-DAY-TRADING-Nasdaq-Futures-Scalping-NQ-Order-Flow-Price-Action-Oct-07__rilljaZdaww.txt

- [ ] L64 `00:05:40` **TRIM** (p=0.39): right? Maybe. Let's go into the houries | **and we can see a little bit more.** | Okay, so yesterday, let's get into  <- FALSE: timeframe/chart talk
- [ ] L73 `00:06:03` **ENTER_LONG** (p=0.30): New York or we'd make a new alltime high | **in the New York session. Very, very** | common. All right. So, we're drifting  <- FALSE: recap of yesterday's expectations
- [ ] L74 `00:06:04` **ENTER_LONG** (p=0.45): in the New York session. Very, very | **common. All right. So, we're drifting** | back off that  <- FALSE: market drifting commentary
- [ ] L187 `00:10:25` **ENTER_LONG** (p=0.28): Goo | **gapping down but uh bearish in** | structure. All right. Looking for a bull  <- FALSE: analysis: looking for a bull flag
- [ ] L204 `00:11:10` **EXIT_ALL** (p=0.40): bit of rotation out of Nvidia, but | **nothing to worry about. Why? Because all** | we're doing is back testing, right? All  <- FALSE: analysis: backtesting commentary
- [ ] L235 `00:12:20` **ENTER_LONG** (p=0.25): doing? PayPal. Looking good. Fantastic. | **Nice breakout on the swing long on** | PayPal. This is what we're talking  <- FALSE: commentary on existing PayPal swing, other instrument
- [ ] L266 `00:13:25` **ENTER_LONG** (p=0.37): in Discord. | **And we look good here.** | Okay, so I'd be very cautious about  <- FALSE: Discord swings wrap-up
- [ ] L296 `00:14:46` **ENTER_LONG** (p=0.31): Cup. Lron, Myron, Paul D, Owen, Richard, | **PB Freak, Investing Library, JJ, good** | morning everyone. Uh, Paul D, is the  <- FALSE: reading subscriber names
- [ ] L569 `00:27:53` **EXIT_ALL** (p=0.37): It's not a good look right now out there | **for Confluence. All right, previous day** | value area high again being tagged here.  <- FALSE: market breadth commentary
- [ ] L591 `00:29:49` **EXIT_ALL** (p=0.37): Yeah, same coupe. Even when I drew that | **out then it was really struggling. Okay,** | ES is stuck. ENQ stuck. We're stuck. No  <- FALSE: market stuck commentary
- [ ] L659 `00:33:02` **ENTER_SHORT** (p=0.33): on AMD, | **1% on Amazon. That thing's sluggish. 7%** | on PayPal, 24% on Oscar Health, and one  <- FALSE: retrospective portfolio recap (already sold)
- [ ] L694 `00:34:51` **ENTER_SHORT** (p=0.28): all these bids on the tape between 230 | **and 215s right now. So passive buyers** | there  <- FALSE: tape reading: passive buyers
- [x] L1486 `01:15:30` **ENTER_SHORT** (p=0.22): you. All right. In it scalp here. Here | **we go. This is the breakdown I was** | looking for. Fantastic. That happened  <- REAL: continuation of real short entry 'In it scalp here' one line earlier
- [ ] L1827 `01:30:31` **EXIT_ALL** (p=0.29): area low, but right now we are building | **out a ton of liquidity here, folks.** | Been here for five plus minutes now. 1 2  <- FALSE: liquidity build-out analysis
- [ ] L2056 `01:40:40` **EXIT_ALL** (p=0.34): liquidity at 211s, it can come and take | **all of that out. So, given the range** | today, it's not that much. is 20 points  <- FALSE: hypothetical: market can take liquidity out
- [ ] L2176 `01:46:23` **ENTER_SHORT** (p=0.28): wanted. I wanted this one. | **Right, we're trading in 93 points of** | range  <- FALSE: range statistics
- [ ] L2329 `01:53:36` **ENTER_LONG** (p=0.23): [Laughter] | **Here's GlobeEx. All right. Asia Asia** | London low now. Take them.  <- FALSE: levels talk; earlier exit is retrospective
- [ ] L2576 `02:08:37` **ENTER_SHORT** (p=0.35): anything. | **Hopefully this is coming now. Go on,** | shove. Go, go, go, go. Fly. I'm not in  <- FALSE: explicitly not in a trade, waiting for shove
- [ ] L2586 `02:09:06` **TRIM** (p=0.28): here and then off with that backside | **move and I'll cover into here and run us** | down if it wants to expand, but it might  <- FALSE: conditional future plan: 'I'll cover into here'
- [ ] L3166 `02:42:00` **ENTER_SHORT** (p=0.31): weekly model, it's all in the course. | **Everything's there. 20 hours on demand** | with a version of the flow zones and  <- FALSE: course advertisement

## 2025-10-23__LIVE-DAY-TRADING-Nasdaq-Futures-Scalping-NQ-Order-Flow-Price-Action-Oct-23__nFvjz1D-Oas.txt

- [ ] L28 `00:03:34` **ENTER_LONG** (p=0.31): back inside. Can it hold? All right. | **Anyone who's done the course weekly** | model, think about what we did yesterday  <- FALSE: course/weekly model talk
- [ ] L127 `00:07:21` **ENTER_SHORT** (p=0.26): right? You've got trapped buyers above. | **There's absolutely no doubt about it.** | Right in here, there is a ton of trapped  <- FALSE: trapped-buyers analysis
- [ ] L690 `00:31:11` **ENTER_SHORT** (p=0.28): now. | **Big seller up at 25,100. 818 lot up** | there right now.  <- FALSE: order book: big seller at 25,100
- [ ] L705 `00:31:53` **ENTER_LONG** (p=0.34): gone red. Complete mixed bag. All right. | **Complete mixed bag. Google the strongest** | one just under 1% up. Weakest one Tesla  <- FALSE: market breadth recap
- [ ] L865 `00:38:51` **ENTER_SHORT** (p=0.28): And that huge buyer was in at 115s. | **Yeah. 100 1,36.** | The delta the delta difference there is  <- FALSE: delta numbers
- [ ] L965 `00:43:21` **ENTER_LONG** (p=0.35): not going to join this long when all | **we're doing is ripping faces upside** | because it's too late. Like we talked  <- FALSE: explicitly NOT joining the long
- [ ] L997 `00:44:52` **ENTER_SHORT** (p=0.34): there's a bigger flush in this. If big | **big big if. All right, here's the edge** | of 150.  <- FALSE: conditional flush analysis
- [ ] L1044 `00:47:02` **ENTER_LONG** (p=0.25): There's no follow through here. | **ES starting to soak up now as well.** | It's impressive. I tell you what, this  <- FALSE: ES soaking commentary
- [x] L1289 `00:58:49` **ENTER_SHORT** (p=0.37): Here we go. Here's VWAP. All right. in | **this short pops. Looking for pops to** | fail. I want some follow through. Come  <- REAL: 'All right. In this short' = real unlabelled short entry
- [ ] L1571 `01:12:12` **ENTER_SHORT** (p=0.25): There you go. There you go. | **Man, this move's so big that Ninja** | Trader can't even catch up.  <- FALSE: platform speed comment
- [ ] L1584 `01:12:52` **EXIT_ALL** (p=0.30): this. We're just thinned right out there | **as well.** | Oh my days.  <- FALSE: explicitly cannot get involved
- [ ] L1958 `01:34:35` **ENTER_LONG** (p=0.26): Should just come and run these stops | **here. There you go. All right. So, can** | it go higher now?  <- FALSE: stop-run market commentary
- [ ] L2002 `01:36:48` **ENTER_LONG** (p=0.53): formed | **parabolic** | trap  <- FALSE: 'parabolic trap wash' market description
- [ ] L2124 `01:42:28` **ENTER_SHORT** (p=0.26): back towards current point of control on | **the session and previous day value area** | high. If they don't bid off this, it  <- FALSE: ES failed-high analysis
- [ ] L2570 `02:07:10` **ENTER_LONG** (p=0.30): Let's just wait and see. Wait and see. | **I'm I'm lacking interest in this. I just** | feel like it's being run by one or two  <- FALSE: explicitly lacking interest
- [ ] L2824 `02:20:14` **EXIT_ALL** (p=0.53): right now who stopped out here. All the | **shorts who stopped out here, they become** | market buyers. And think about breakout  <- FALSE: educational: other traders' stops
- [ ] L2900 `02:23:52` **ENTER_SHORT** (p=0.27): right, if they've got enough out, they | **might not support this bid. Remember,** | they've been supporting the bid down  <- FALSE: bid-support analysis
- [ ] L3014 `02:29:51` **ENTER_LONG** (p=0.29): chilling in this market. Yeah, but right | **thing to do.** | Right thing to do.  <- FALSE: made daily goal, chilling
- [ ] L3068 `02:32:18` **ENTER_SHORT** (p=0.28): [ __ ] go. Absolutely destroyed that. | **[Laughter]** | [Music]  <- FALSE: [Laughter]
- [ ] L3404 `02:49:12` **ENTER_SHORT** (p=0.35): There's stuff on anchor viewups, volume | **profile,** | uh flow zones, like loads and loads and  <- FALSE: channel advertisement

## 2025-11-06__LIVE-DAY-TRADING-Nasdaq-Futures-Scalping-NQ-Order-Flow-Price-Action-Nov-06__Luatve1nc1M.txt

- [ ] L218 `00:12:30` **ENTER_LONG** (p=0.28): All right. So, you can see the gap's | **nice and nice and clear up there. In** | fact, let's do an alert on that just so  <- FALSE: setting a chart alert, not a trade
- [ ] L356 `00:18:07` **ENTER_LONG** (p=0.52): Peter, Illis, Peter, Curry, Chris, | **Thorne, Larry, Mo, Firewater, GG, Ron,** | Owen, Lou, Erf, Awani, Charles, Lero,  <- FALSE: reading subscriber names
- [ ] L437 `00:22:03` **ENTER_LONG** (p=0.34): here. | **So yeah, Google finding a bit of a big** | everything else and Nvidia everything  <- FALSE: Google bid analysis
- [ ] L454 `00:22:57` **EXIT_ALL** (p=0.28): they're going to take GloEx out here at | **the moment. Looks like it back towards** | low of day.  <- FALSE: market taking out GlobEx analysis
- [ ] L483 `00:24:22` **EXIT_ALL** (p=0.35): very good. All right, this 6 a.m. still | **looks good for taking this out right** | now. Here we go. Waiting to see if  <- FALSE: level take-out talk, waiting
- [~] L514 `00:25:42` **TRIM** (p=0.30): Do I take a bit more? | **Don't want to get stuck down here,** | folks. Do not want to get stuck down  <- AMBIGUOUS: in a short, 'Do I take a bit more?' deliberation, no executed action
- [ ] L888 `00:42:46` **MOVE_STOP** (p=0.22): buyers trapped up uh 600. | **So actually, we left buyers trapped** | because they tried to buy that last dip.  <- FALSE: trapped-buyers analysis
- [~] L954 `00:46:19` **ENTER_SHORT** (p=0.22): sure it's accurate. Sorry. Thanks. | **Okay, so just down to small size now.** | Well, hopefully, especially those in  <- AMBIGUOUS: 'down to small size now' implies a recent trim but no explicit execution
- [~] L1069 `00:51:59` **MOVE_STOP** (p=0.23): earnings. | **New lows coming. I got to move that man.** | We're moving fast. We are moving fast  <- AMBIGUOUS: 'I got to move that man' possibly moving his stop, unclear referent
- [ ] L1095 `00:53:26` **ENTER_SHORT** (p=0.24): Do not bid on this market. You | **definitely don't get short on the lows,** | but do not bid on this market. All  <- FALSE: second-person advice: don't bid this market
- [ ] L1113 `00:54:07` **TRIM** (p=0.22): got completed. Right, think about this | **what we talked about those in Discord.** | Have a look if you haven't looked. Look  <- FALSE: Discord recap
- [x] L1179 `00:56:57` **TRIM** (p=0.32): But I had to pay myself there, folks. | **Okay, while we cool off, let's uh let me** | uh go through all the chats. Sorry,  <- REAL: 'I had to pay myself there, folks' = real trim seconds earlier, in context window
- [ ] L1189 `00:57:32` **ENTER_SHORT** (p=0.30): Where do I get VIX data from? I just | **normal data. I I don't use it on just on** | Trading View, mate. On Trading View.  <- FALSE: viewer Q&A about VIX data
- [~] L1897 `01:31:04` **ENTER_SHORT** (p=0.46): bulls now stuck about above 60 again. | **Trading underneath. Here we go. Come on.** | Need the seller. These sellers are  <- AMBIGUOUS: holding a short ('I'll cover it'), no new action at this moment
- [ ] L2681 `02:10:02` **EXIT_ALL** (p=0.28): Is there a much lower? No, | **no one really hanging out lower yet. I** | just think they're looking for a sweep  <- FALSE: order book commentary
- [ ] L2785 `02:15:32` **ENTER_SHORT** (p=0.24): the puke out and then reshorted in here | **for this move. Okay. And I got stopped** | out in 60s in here. So we've had one,  <- FALSE: retrospective recap of the day's shorts and stop-outs
- [ ] L3017 `02:25:57` **EXIT_ALL** (p=0.32): like 220. So let's mark this out. 220 to | **180 on 220** | like 220 to 180. This kind of box here  <- FALSE: marking levels for a runner
- [ ] L3417 `02:47:29` **EXIT_ALL** (p=0.47): there we go | **yeah running out of reasons to go lower** | for for me unless it's panic  <- FALSE: running out of reasons commentary
- [ ] L3594 `02:56:20` **EXIT_ALL** (p=0.28): No one's done it. | **>> No one's ever done it. I've done it.** | >> Okay. It's pretty low.  <- FALSE: chat banter
- [ ] L3685 `03:01:18` **TRIM** (p=0.27): really nice. Looks really good here. So, | **into this edge. You can see the volume** | starts here, folks. So if you mark out  <- FALSE: second-person advice: make sure you grabbed some

## 2025-11-07__LIVE-DAY-TRADING-Nasdaq-Futures-Scalping-NQ-Order-Flow-Price-Action-Nov-07__KUhMYgRYfE8.txt

- [ ] L286 `00:13:32` **ENTER_SHORT** (p=0.28): Slight gap down in the market. | **Okay.** | >> [snorts]  <- FALSE: 'Okay.' nothing
- [ ] L369 `00:17:05` **ENTER_LONG** (p=0.25): than Apple the only one holding up. | **There has been fear in this market. So,** | let's just wait and see.  <- FALSE: wait and see
- [ ] L416 `00:18:56` **ENTER_SHORT** (p=0.22): open like always. Let me get my anchor | **on before I forget.** | No, that would be a fib.  <- FALSE: placing an anchored VWAP indicator
- [ ] L534 `00:24:31` **EXIT_ALL** (p=0.42): this right now. They are scared out of | **their souls at the moment. It's the** | first time we've seen a bid step in as  <- FALSE: fear commentary
- [ ] L827 `00:38:27` **EXIT_ALL** (p=0.24): 21s. | **So VIX now building out a range** | buyers trying to step in here back to  <- FALSE: VIX range analysis
- [ ] L900 `00:41:32` **ENTER_LONG** (p=0.25): 60 is where I got in. | **Buying quarter those highs at the** | moment. Be careful. I think there's more  <- FALSE: buyers-caught commentary; runner talk is conditional
- [ ] L924 `00:42:39` **EXIT_ALL** (p=0.24): bucks no matter what. | **I think it's coming. I think a little** | squeeze out is coming here. They've got  <- FALSE: prediction talk; locked profit is state, not action
- [~] L950 `00:43:58` **TRIM** (p=0.29): Here we go. | **Getting close into this low volume node.** | Nothing wrong with taking some profit in  <- AMBIGUOUS: 'nothing wrong with taking some profit' advice-flavoured, unclear if executed
- [ ] L965 `00:44:37` **ENTER_LONG** (p=0.23): the world, right? Don't expect the | **world. But we have drifted very, very** | low into higher time frame areas of  <- FALSE: demand-zone analysis
- [ ] L1034 `00:47:23` **ENTER_LONG** (p=0.37): up. | **Okay.** | Well, I can't imagine consumer sentiment  <- FALSE: echo of already-labelled exit at L1030; no new action
- [ ] L1080 `00:49:49` **ENTER_LONG** (p=0.25): footprint and bookmat. | **Apple finding a bid here, folks. Now** | over a third of percent up. So relative  <- FALSE: Apple bid + coffee
- [ ] L1296 `00:59:51` **TRIM** (p=0.30): profit. Congratulations. Yeah, I mean if | **you're locking in money playing in a** | range on a Friday like this, I think  <- FALSE: praising viewers locking profit
- [ ] L1311 `01:00:21` **EXIT_ALL** (p=0.21): and the 24-hour VWAP which is up there | **right the way at 50 25,112.** | So higher day. If we can get through  <- FALSE: target levels
- [ ] L1329 `01:01:17` **EXIT_ALL** (p=0.21): got it. B, you got it. Troy got it. | **Psychosis. Stefan, Charles, Tyson,** | Brris. Nice. We look good here. Just  <- FALSE: viewer names + second-person advice
- [ ] L1346 `01:02:11` **EXIT_ALL** (p=0.23): because how we're building liquidity is | **not particularly bullish right now.** | Let's see. They might have caught  <- FALSE: liquidity analysis
- [ ] L1484 `01:08:06` **EXIT_ALL** (p=0.23): seller up there. [snorts] | **Am I also on video on Discord? No, we** | Well, we do private lessons on video.  <- FALSE: Discord Q&A
- [ ] L2492 `02:03:16` **EXIT_ALL** (p=0.51): getting booted out of the stream. | **You will It's not for me. It's because** | there are new traders in here and they  <- FALSE: moderating chat
- [ ] L2607 `02:10:56` **ENTER_LONG** (p=0.26): small size and house money. | **Buyers got stuck there again on that** | last push to 44s. I want to dip back  <- FALSE: analysis; entry was 11 lines earlier and labelled
- [ ] L2771 `02:23:07` **ENTER_LONG** (p=0.46): playing now. | **Okay.** | SPX level. Yeah. Six 6 660 right on Q  <- FALSE: 'Okay.' + SPX levels
- [ ] L3103 `02:39:43` **ENTER_LONG** (p=0.23): account 595. | **So, my big boy account I'm up uh three** | grand on. Uh that account I'm up 595 on  <- FALSE: account P&L recap

## 2025-11-14__LIVE-DAY-TRADING-Nasdaq-Futures-Scalping-NQ-Order-Flow-Price-Action-Nov-14__PG2wjhIe-f4.txt

- [ ] L337 `00:16:30` **ENTER_LONG** (p=0.32): Jesse, Jeff, Garbs, Chad, Noah, Clint, | **Info, Risk, Dumper, Christy, Futures** | Withdrew, Christh, Miguel, Peter, Larry,  <- FALSE: reading subscriber names
- [ ] L742 `00:36:36` **ENTER_LONG** (p=0.27): here this morning. | **Okay, nice. Keep going. Higher the** | better.  <- FALSE: cheering price toward levels
- [ ] L765 `00:37:49` **ENTER_SHORT** (p=0.38): fail right here right now. | **Not much excess there. Some strong** | selling coming in though.  <- FALSE: excess/selling analysis
- [ ] L1058 `00:50:24` **ENTER_LONG** (p=0.30): very risky because we've not fulfilled | **the obligation. Now we've got this close** | to taking all this. we might as well  <- FALSE: hypothetical short risk analysis
- [ ] L1228 `00:57:24` **ENTER_LONG** (p=0.32): PC here. This this candle structure here | **is really bad. All right. So on** | basically from 63 we have a void from 63  <- FALSE: volume void analysis
- [ ] L1419 `01:05:12` **ENTER_SHORT** (p=0.29): Spider's still got a way to go to get to | **previous day low.** | Relative strength Apple and Microsoft.  <- FALSE: levels
- [ ] L1425 `01:05:26` **ENTER_SHORT** (p=0.31): We've got no excess up there. Go on. Get | **your get your ass up now.** | Hands off the mouse. Off the mouse.  <- FALSE: yelling at the market
- [ ] L1803 `01:21:43` **ENTER_SHORT** (p=0.36): notice the problem now is even if we get | **this short here, we have to respect** | this. Once we leave this, it gets really  <- FALSE: hypothetical short, explicitly not looking to short yet
- [ ] L2079 `01:34:14` **ENTER_SHORT** (p=0.28): above the teens, all right, is not a | **risk-on scenario. It's a high risk** | scenario. Is a riskoff scenario, but  <- FALSE: VIX risk analysis
- [ ] L2413 `01:50:05` **ENTER_SHORT** (p=0.25): this gray box. Uh this little shelf | **we're on here. That's your sort of new** | node. We can move this down. Look here.  <- FALSE: node analysis
- [ ] L2760 `02:08:01` **ENTER_LONG** (p=0.34): Um so I have I'm trying trying an | **account there at the moment. I've got it** | passed.  <- FALSE: prop account talk
- [ ] L2870 `02:13:07` **ENTER_SHORT** (p=0.28): We're We're there. All right. So, we've | **not pushed above and held yet. Right.** | It's got to hold this level. And then  <- FALSE: reclaim analysis
- [ ] L3087 `02:22:14` **EXIT_ALL** (p=0.49): about. Get out of my way. Leave the | **tape.** | You fraud.  <- FALSE: yelling at spoofer while holding; no action
- [ ] L3224 `02:28:47` **EXIT_ALL** (p=0.33): Running out of time. We got 20 minutes | **till lunch.** | And this thing is still in an absolute  <- FALSE: schedule talk
- [ ] L3266 `02:30:43` **ENTER_SHORT** (p=0.23): nice. Got to let go of previous day | **point of control. Going to keep** | absorbing here.  <- FALSE: absorption analysis
- [ ] L3321 `02:33:23` **ENTER_SHORT** (p=0.33): Let's go. | **[ __ ] puke it. Wreck these balls. Go,** | go, go, go, go. Go down to previous week  <- FALSE: cheering the move
- [ ] L3755 `02:52:09` **EXIT_ALL** (p=0.37): the exhaustion is whether they can build | **out on it. Friday's session showed** | showed signs of exhaustion at the lows,  <- FALSE: reading written recap aloud
- [ ] L3914 `02:59:19` **ENTER_SHORT** (p=0.27): Let's uh | **measure this.** | Well, top of the gap looks uh probable  <- FALSE: measuring the chart
- [ ] L3922 `02:59:53` **ENTER_SHORT** (p=0.37): bear in this | **back in the day? I'm telling you, that** | would have been me. I would have been  <- FALSE: anecdote about being a stubborn bear
- [ ] L3964 `03:01:33` **ENTER_SHORT** (p=0.25): No, I don't I don't use a 50 | **SMA on a one minute. Don't use any SMAs** | on the one minute.  <- FALSE: indicator Q&A
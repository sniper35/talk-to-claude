## Goal

Build a functionality with a terminal plugin, mac app, cli command etc you name it, as long as it can do the following task so I can use my voice to interact with the (multiple) claude code terminals:

## When I open claude code and use the command /start-audio to turn on functionality:  I can talk to the claude to as my response when claude needs my input. For the voice -> text parse, you can use all available solutions, assume I can get accounts api/secrets set up for any service you need to use(Eleven Labs etc, you name it, use the service providing the best quality, don't consider the cost). The audio to text conversion needs to recognize the following cases besides the normal text:

1. If there are multiple claude code windows splitted in one window. I can say 'activate left upper window', then the cursor/mouse will move to and activate the left upper window of the iterm terminal(Assuem I have split the iTerm terminal into multiple windows), and then use my following voice text into the clauded code as my input.  
2. If there is just one claude code window open, I don't need to say 'activate ....', it will go to the only one claude code window and use my voice as inputs.
3. I can say 'end voice'(or any other more proper words) as a stop signal that I finish the current voice input. Then claude code should start to work. Until it needs new input, and then go back to step #1. 

## I use the command /stop-audio to stop the audio to text functionality.
- 
-  

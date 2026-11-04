# UR3e simulator through Docker Desktop. Interface: http://localhost:6080/vnc.html
# In .env set ROBOT_MODE=ursim and ROBOT_HOST=127.0.0.1, then power on the robot in the simulator.
docker run --rm -it -e ROBOT_MODEL=UR3 `
  -p 5900:5900 -p 6080:6080 -p 29999:29999 -p 30001-30004:30001-30004 `
  universalrobots/ursim_e-series

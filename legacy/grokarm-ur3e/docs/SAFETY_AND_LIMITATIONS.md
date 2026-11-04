# Safety and limitations

This is a hackathon prototype and not a certified safety system.

- The physical e-stop, controller safety settings and staff supervision are the safety layer. They stay active in every test.
- `stopJ` is a normal control command. Voice recognition and networks have no guaranteed timing.
- Hardware work happens only in a staffed slot.

## Before any real motion

- [ ] Staff confirm the robot, network, control method and e-stop operator.
- [ ] Staff approve the poses, speed and acceleration.
- [ ] `config/poses.local.yaml` has `target: real` and `approved_by` filled in.
- [ ] `ALLOW_REAL_MOTION=STAFF_APPROVED` is set for this slot, then cleared.
- [ ] The work area is clear.

Never copy the simulator poses, library example values or default home angles to the arm.

## Guards in the software

- Only enabled skills reach the model. There is no field for coordinates or speed.
- The real adapter refuses poses unless `target` is `real` and `approved_by` is set.
- A skill starts only from a known pose, within tolerance.
- Faults, timeouts or lost connections end the skill and block new motion until the robot reports ready.
- A lost voice link during motion stops the arm.

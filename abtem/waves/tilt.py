from typing import Union, TYPE_CHECKING, Tuple, List

import dask.array as da

from abtem.core.axes import TiltAxis, AxisMetadata
from abtem.core.backend import get_array_module
from abtem.core.distributions import Distribution, AxisAlignedDistributionND
from abtem.waves.transfer import (
    WaveTransform,
    EnsembleFromDistributionsMixin,
    CompositeWaveTransform,
)

if TYPE_CHECKING:
    from abtem.waves.waves import Waves


def validate_tilt(tilt):
    if isinstance(tilt, Distribution):
        if not isinstance(tilt, AxisAlignedDistributionND):
            raise NotImplementedError()

        return tilt

    elif isinstance(tilt, (tuple, list)):
        assert len(tilt) == 2

        transforms = []
        for tilt_component, direction in zip(tilt, ("x", "y")):
            transforms.append(
                AxisAlignedBeamTilt(tilt=tilt_component, direction=direction)
            )

        tilt = CompositeWaveTransform(transforms)

    return tilt



class AxisAlignedBeamTilt(EnsembleFromDistributionsMixin, WaveTransform):
    def __init__(self, tilt: Union[float, Distribution] = 0.0, direction: str = "x"):
        if not isinstance(tilt, Distribution):
            tilt = float(tilt)
        self._tilt = tilt
        self._direction = direction
        self._distributions = ("tilt",)

    @property
    def direction(self):
        return self._direction

    @property
    def tilt(self) -> Union[float, Distribution]:
        """Beam tilt [mrad]."""
        return self._tilt

    @property
    def metadata(self):
        if isinstance(self.tilt, Distribution):
            return {f"base_tilt_{self._direction}": 0.0}
        else:
            return {f"base_tilt_{self._direction}": self._tilt}

    @property
    def ensemble_axes_metadata(self) -> List[AxisMetadata]:
        if isinstance(self.tilt, Distribution):
            return [
                TiltAxis(
                    label=f"tilt_{self._direction}",
                    values=tuple(self.tilt.values),
                    direction=self._direction,
                    units="mrad",
                    _ensemble_mean=self.tilt.ensemble_mean,
                )
            ]
        else:
            return []

    def apply(self, waves: "Waves") -> "Waves":
        xp = get_array_module(waves.device)

        array = waves.array[(None,) * self.ensemble_dims]

        if waves.is_lazy:
            array = da.tile(array, self.ensemble_shape + (1,) * len(waves.shape))
        else:
            array = xp.tile(array, self.ensemble_shape + (1,) * len(waves.shape))

        kwargs = waves.copy_kwargs(exclude=("array",))
        kwargs["array"] = array
        kwargs["metadata"] = {**kwargs["metadata"], **self.metadata}
        kwargs["ensemble_axes_metadata"] = (
            self.ensemble_axes_metadata + kwargs["ensemble_axes_metadata"]
        )
        return waves.__class__(**kwargs)

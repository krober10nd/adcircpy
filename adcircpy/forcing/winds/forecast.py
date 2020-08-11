from datetime import datetime, timedelta
from functools import lru_cache
import pathlib

from haversine import haversine
from matplotlib import pyplot
from matplotlib.transforms import Bbox
import numpy
from pandas import DataFrame
from pyproj import CRS, Proj
from shapely.geometry import Point, Polygon
from tropycal.realtime import Realtime

from adcircpy.forcing.winds import atcf_id
from adcircpy.forcing.winds.base import WindForcing


class NHCAdvisory(WindForcing):
    storms = Realtime()

    def __init__(self, storm_id: str, start_date: datetime = None, end_date: datetime = None,
                 crs: CRS = None):
        self._storm_id = storm_id
        super().__init__(start_date, end_date, crs)

    def clip_to_bbox(self, bbox: Bbox):
        """
        Important: bbox must be expressed in Mercator projection (EPSG:3395)
        """
        assert isinstance(bbox, Bbox), f"bbox must be a {Bbox} instance."
        bbox_pol = Polygon([
            [bbox.xmin, bbox.ymin],
            [bbox.xmax, bbox.ymin],
            [bbox.xmax, bbox.ymax],
            [bbox.xmin, bbox.ymax],
            [bbox.xmin, bbox.ymin]
        ])
        _switch = True
        unique_dates = numpy.unique(self._df['datetime'])
        for _datetime in unique_dates:
            records = self._df[self._df['datetime'] == _datetime]
            radii = records['radius_of_last_closed_isobar'].iloc[0]
            radii = 1852. * radii  # convert to meters
            merc = Proj("EPSG:3395")
            x, y = merc(
                records['longitude'].iloc[0],
                records['latitude'].iloc[0])
            p = Point(x, y)
            pol = p.buffer(radii)
            if _switch:
                if not pol.intersects(bbox_pol):
                    continue
                else:
                    self.start_date = records['datetime'].iloc[0]
                    _switch = False
                    continue
                    # self.start_date = 
            else:
                if pol.intersects(bbox_pol):
                    continue
                else:
                    self.end_date = records['datetime'].iloc[0]
                    break

    def plot_trajectory(self, ax: pyplot.Axes = None, show: bool = False, color='k', **kwargs):
        kwargs.update({'color': color})
        if ax is None:
            fig = pyplot.figure()
            ax = fig.add_subplot(111)
        for i in range(len(self.speed)):
            # when dealing with nautical degrees, U is sine and V is cosine.
            U = self.speed.iloc[i] * numpy.sin(numpy.deg2rad(self.direction.iloc[i]))
            V = self.speed.iloc[i] * numpy.cos(numpy.deg2rad(self.direction.iloc[i]))
            ax.quiver(
                self.longitude.iloc[i], self.latitude.iloc[i], U, V, **kwargs)
            ax.annotate(
                self.data_frame['datetime'].iloc[i],
                (self.longitude.iloc[i], self.latitude.iloc[i])
            )
        if show:
            ax.axis('scaled')
            pyplot.show()

    def write(self, path: str, overwrite: bool = False):
        path = pathlib.Path(path)
        if path.is_file() and not overwrite:
            raise Exception('Files exist, set overwrite=True to allow overwrite.')
        with open(path, 'w') as f:
            f.write(self.fort22)

    @property
    def storm_id(self):
        return self._storm_id

    @property
    def _storm_id(self):
        return self.__storm_id

    @_storm_id.setter
    def _storm_id(self, storm_id):
        num_digits = len([char for char in storm_id if char.isdigit()])
        # check if only year is supplied
        if num_digits == 4:
            id = atcf_id(storm_id)
            if id is None:
                raise Exception(f'No storm with id "{storm_id}"')
            storm_id = id

        self.storm = self.storms.get_storm(storm_id)
        self.__storm_id = storm_id

    @property
    def _start_date(self):
        return self.__start_date

    @_start_date.setter
    def _start_date(self, start_date):
        if start_date is not None:
            assert isinstance(start_date, datetime)
        else:
            start_date = self._df['datetime'].iloc[0]
        assert self._df['datetime'].iloc[0] <= start_date < self._df['datetime'].iloc[-1], \
            f"start_date must be {self._df['datetime'].iloc[0]} <= start_date ({start_date}) < " \
            f"{self._df['datetime'].iloc[-1]}"
        self.__start_date = start_date

    @property
    def _end_date(self):
        return self.__end_date

    @_end_date.setter
    def _end_date(self, end_date):
        if end_date is not None:
            assert isinstance(end_date, datetime)
        else:
            end_date = self._df['datetime'].iloc[-1]
        assert self._df['datetime'].iloc[0] < end_date <= self._df['datetime'].iloc[-1], \
            f"end_date must be {self._df['datetime'].iloc[0]} <= end_date ({end_date}) <= " \
            f"{self._df['datetime'].iloc[-1]}"
        assert end_date > self.start_date, \
            f"end_date ({end_date}) must be after start_date ({self.start_date})"
        self.__end_date = end_date

    @property
    def name(self):
        return self.data_frame['name'].value_counts()[:].index.tolist()[0]

    @property
    def basin(self):
        return self.data_frame['basin'].iloc[0]

    @property
    def storm_number(self):
        return self.data_frame['storm_number'].iloc[0]

    @property
    def year(self):
        return self.data_frame['datetime'].iloc[0].year

    @property
    def datetime(self):
        return self.data_frame['datetime']

    @property
    def speed(self):
        return self.data_frame['speed']

    @property
    def direction(self):
        return self.data_frame['direction']

    @property
    def longitude(self):
        return self.data_frame['longitude']

    @property
    def latitude(self):
        return self.data_frame['latitude']

    @property
    @lru_cache(maxsize=None)
    def data_frame(self):
        return self._df[(self._df['datetime'] >= self.start_date) &
                        (self._df['datetime'] <= self._file_end_date)]

    @property
    def _df(self):
        # https://www.nrlmry.navy.mil/atcf_web/docs/database/new/abdeck.txt
        try:
            return self.__df
        except AttributeError:
            historic_data = {
                "basin"                       : self.storm['wmo_basin'],
                "storm_number"                : int(self.storm['id'][2:4]),
                "datetime"                    : self.storm['date'],
                "record_type"                 : self.storm['special'],
                "latitude"                    : self.storm['lat'],
                "longitude"                   : self.storm['lon'],
                "max_sustained_wind_speed"    : self.storm['vmax'],
                "central_pressure"            : self.storm['mslp'],
                "development_level"           : self.storm['type'],
                "isotach"                     : None,
                "quadrant"                    : None,
                "radius_for_NEQ"              : None,
                "radius_for_SEQ"              : None,
                "radius_for_SWQ"              : None,
                "radius_for_NWQ"              : None,
                "background_pressure"         : None,
                "radius_of_last_closed_isobar": None,
                "radius_of_maximum_winds"     : None,
                "name"                        : self.storm['name'],
                "direction"                   : None,
                "speed"                       : None
            }
            historic_data = self._compute_velocity(historic_data)
            forecast = self.storm.get_forecast_realtime()
            forecast_data = {
                "basin"                       : self.storm['wmo_basin'],
                "storm_number"                : int(self.storm['id'][2:4]),
                "datetime"                    : self.storm['date'],
                "record_type"                 : self.storm['special'],
                "latitude"                    : self.storm['lat'],
                "longitude"                   : self.storm['lon'],
                "max_sustained_wind_speed"    : self.storm['vmax'],
                "central_pressure"            : self.storm['mslp'],
                "development_level"           : self.storm['type'],
                "isotach"                     : None,
                "quadrant"                    : None,
                "radius_for_NEQ"              : None,
                "radius_for_SEQ"              : None,
                "radius_for_SWQ"              : None,
                "radius_for_NWQ"              : None,
                "background_pressure"         : None,
                "radius_of_last_closed_isobar": None,
                "radius_of_maximum_winds"     : None,
                "name"                        : self.storm['name'],
                "direction"                   : None,
                "speed"                       : None
            }
            forecast_data = self._compute_velocity(forecast_data)
            # data = self._transform_coordinates(data)
            self.__df = DataFrame(data=historic_data)
            return self.__df

    @property
    def fort22(self):
        record_number = self._generate_record_numbers()
        fort22 = ''
        for i, (_, row) in enumerate(self.data_frame.iterrows()):
            longitude = row['longitude']
            latitude = row['latitude']
            if longitude >= 0:
                longitude = f'{int(longitude / 0.1):>5}E'
            else:
                longitude = f'{int(longitude / -0.1):>5}W'
            if latitude >= 0:
                latitude = f'{int(latitude / 0.1):>4}N'
            else:
                latitude = f'{int(latitude / -0.1):>4}S'
            row['longitude'] = longitude
            row['latitude'] = latitude

            background_pressure = row['background_pressure']
            if background_pressure is None:
                background_pressure = self.data_frame['background_pressure'].iloc[i - 1]
            if background_pressure is not None:
                if background_pressure <= row['central_pressure'] < 1013:
                    background_pressure = 1013
                elif background_pressure <= row['central_pressure'] >= 1013:
                    background_pressure = int(row['central_pressure'] + 1)
                else:
                    background_pressure = int(row['background_pressure'])
            else:
                background_pressure = ''
            row['background_pressure'] = background_pressure

            row.extend([
                # BASIN - basin, e.g. WP, IO, SH, CP, EP, AL, SL
                f'{row["basin"]:<2}',
                # CY - annual cyclone number: 1 through 99
                f'{row["storm_number"]:>3}',
                # YYYYMMDDHH - Warning Date-Time-Group: 0000010100 through 9999123123. (note, 4 digit year)
                f'{format(row["datetime"], "%Y%m%d%H"):>11}',
                # TECHNUM/MIN - objective technique sorting number, minutes for best track: 00 - 99
                f'{"":3}',
                # TECH - acronym for each objective technique or CARQ or WRNG, BEST for best track.
                f'{row["record_type"]:>5}',
                # TAU - forecast period: -24 through 240 hours, 0 for best-track, negative taus used for CARQ and WRNG records.
                f'{int((row["datetime"] - self.start_date) / timedelta(hours=1)):>4}',
                # LatN/S - Latitude (tenths of degrees) for the DTG: 0 through 900, N/S is the hemispheric index.
                f'{latitude:>5}',
                # LonE/W - Longitude (tenths of degrees) for the DTG: 0 through 1800, E/W is the hemispheric index.
                f'{longitude:>5}',
                # VMAX - Maximum sustained wind speed in knots: 0 through 300.
                f'{int(row["max_sustained_wind_speed"]):>4}',
                # MSLP - Minimum sea level pressure, 1 through 1100 MB.
                f'{int(row["central_pressure"]):>5}',
                # TY - Level of tc development:
                f'{row["development_level"] if row["development_level"] is not None else "":>3}',
                # RAD - Wind intensity (kts) for the radii defined in this record: 34, 50, 64.
                f'{int(row["isotach"]) if row["isotach"] is not None else "":>4}',
                # WINDCODE - Radius code: AAA - full circle, QQQ - quadrant (NNQ, NEQ, EEQ, SEQ, SSQ, SWQ, WWQ, NWQ)
                f'{row["quadrant"] if row["quadrant"] is not None else "":>4}',
                # RAD1 - If full circle, radius of specified wind intensity, If semicircle or quadrant, radius of specified wind intensity of circle portion specified in radius code. 0 - 1200 nm.
                f'{int(row["radius_for_NEQ"]) if row["radius_for_NEQ"] is not None else "":>5}',
                # RAD2 - If full circle this field not used, If semicicle, radius (nm) of specified wind intensity for semicircle not specified in radius code, If quadrant, radius (nm) of specified wind intensity for 2nd quadrant (counting clockwise from quadrant specified in radius code). 0 through 1200 nm.
                f'{int(row["radius_for_SEQ"]) if row["radius_for_SEQ"] is not None else "":>5}',
                # RAD3 - If full circle or semicircle this field not used, If quadrant, radius (nm) of specified wind intensity for 3rd quadrant (counting clockwise from quadrant specified in radius code). 0 through 1200 nm.
                f'{int(row["radius_for_SWQ"]) if row["radius_for_SWQ"] is not None else "":>5}',
                # RAD4 - If full circle or semicircle this field not used, If quadrant, radius (nm) of specified wind intensity for 4th quadrant (counting clockwise from quadrant specified in radius code). 0 through 1200 nm.
                f'{int(row["radius_for_NWQ"]) if row["radius_for_NWQ"] is not None else "":>5}',
                # RADP - pressure in millibars of the last closed isobar, 900 - 1050 mb.
                f'{row["background_pressure"]:>5}',
                # RRP - radius of the last closed isobar in nm, 0 - 9999 nm.
                f'{int(row["radius_of_last_closed_isobar"]) if row["radius_of_last_closed_isobar"] is not None else "":>5}',
                # MRD - radius of max winds, 0 - 999 nm.
                f'{int(row["radius_of_maximum_winds"]) if row["radius_of_maximum_winds"] is not None else "":>4}'
                # GUSTS - gusts, 0 through 995 kts.
                f'{"":>5}',
                # EYE - eye diameter, 0 through 999 nm.
                f'{"":>4}',
                # SUBREGION - subregion code: W, A, B, S, P, C, E, L, Q.
                f'{"":>4}',
                # MAXSEAS - max seas: 0 through 999 ft.
                f'{"":>4}',
                # INITIALS - Forecaster's initials, used for tau 0 WRNG, up to 3 chars.
                f'{"":>4}',
                # DIR - storm direction in compass coordinates, 0 - 359 degrees.
                f'{row["direction"] if row["direction"] is not None else "":>3}',
                # SPEED - storm speed, 0 - 999 kts.
                f'{row["speed"]:>4}',
                # STORMNAME - literal storm name, NONAME or INVEST. TCcyx used pre-1999, where:
                f'{row["name"]:^12}',
                # from this point forwards it's all aswip
                f'{record_number[i]:>4}'
            ])
            row = ','.join(row)
            fort22 += f'{row}\n'
        return fort22

    @property
    def WTIMINC(self):
        return f'{self.start_date:%Y %m %d %H} ' \
               f'{self.data_frame["storm_number"].iloc[0]} {self.BLADj} {self.geofactor}'

    @property
    def BLADj(self):
        try:
            return self.__BLADj
        except AttributeError:
            return 0.9

    @BLADj.setter
    def BLADj(self, BLADj: float):
        BLADj = float(BLADj)
        assert 0 <= BLADj <= 1
        self.__BLADj = BLADj

    @property
    def geofactor(self):
        try:
            return self.__geofactor
        except AttributeError:
            return 1

    @geofactor.setter
    def geofactor(self, geofactor: float):
        geofactor = float(geofactor)
        assert 0 <= geofactor <= 1
        self.__geofactor = geofactor

    def _generate_record_numbers(self):
        record_number = [1]
        for i in range(1, len(self.datetime)):
            if self.datetime.iloc[i] == self.datetime.iloc[i - 1]:
                record_number.append(record_number[-1])
            else:
                record_number.append(record_number[-1] + 1)
        return record_number

    @property
    def _file_end_date(self):
        unique_dates = numpy.unique(self._df['datetime'])
        for date in unique_dates:
            if date >= self.end_date:
                return date

    @staticmethod
    def _compute_velocity(data: {}):
        """
        Output has units of meters per second.
        """

        if data['direction'] is None:
            data['direction'] = []
        if data['speed'] is None:
            data['speed'] = []

        merc = Proj("EPSG:3395")
        x, y = merc(data['longitude'], data['latitude'])
        t = data['datetime']
        unique_datetimes = numpy.unique(t)
        for i, _datetime in enumerate(unique_datetimes):
            indexes, = numpy.where(numpy.asarray(t) == _datetime)
            for idx in indexes:
                if indexes[-1] + 1 < len(t):
                    dx = haversine((y[idx], x[indexes[-1] + 1]), (y[idx], x[idx]), unit='nmi')
                    dy = haversine((y[indexes[-1] + 1], x[idx]), (y[idx], x[idx]), unit='nmi')
                    dt = ((t[indexes[-1] + 1] - t[idx]) / timedelta(hours=1))
                    vx = numpy.copysign(dx / dt, x[indexes[-1] + 1] - x[idx])
                    vy = numpy.copysign(dy / dt, y[indexes[-1] + 1] - y[idx])
                else:
                    dx = haversine((y[idx], x[indexes[0] - 1]), (y[idx], x[idx]), unit='nmi')
                    dy = haversine((y[indexes[0] - 1], x[idx]), (y[idx], x[idx]), unit='nmi')
                    dt = ((t[idx] - t[indexes[0] - 1]) / timedelta(hours=1))
                    vx = numpy.copysign(dx / dt, x[idx] - x[indexes[0] - 1])
                    vy = numpy.copysign(dy / dt, y[idx] - y[indexes[0] - 1])
                bearing = (360. + numpy.rad2deg(numpy.arctan2(vx, vy))) % 360
                speed = numpy.sqrt(dx ** 2 + dy ** 2) / dt
                data['direction'].append(int(numpy.around(bearing, 0)))
                data['speed'].append(int(numpy.around(speed, 0)))
        return data


if __name__ == '__main__':
    advisory = NHCAdvisory('AL092020')
    data_frame = advisory.data_frame
    # fort22 = advisory.fort22

    print('done')
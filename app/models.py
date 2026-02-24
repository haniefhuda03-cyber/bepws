from . import db
from sqlalchemy import Column, Index, Integer, Float, String, ForeignKey, func
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP
from sqlalchemy.orm import relationship
from datetime import datetime, timezone


class Model(db.Model):
    __tablename__ = "model"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    range_prediction = Column(Integer, nullable=False)

    def __repr__(self):
        return f"<Model id={self.id} name={self.name} range_prediction={self.range_prediction}>"

    def to_dict(self):
        return {"id": self.id, "name": self.name, "range_prediction": self.range_prediction}


class Label(db.Model):
    __tablename__ = "label"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)

    def __repr__(self):
        return f"<Label id={self.id} name={self.name}>"

    def to_dict(self):
        return {"id": self.id, "name": self.name}


class WeatherLogWunderground(db.Model):
    __tablename__ = "weather_log_wunderground"
    id = Column(Integer, primary_key=True, autoincrement=True)
    solar_radiation = Column(Float, nullable=True)
    ultraviolet_radiation = Column(Float, nullable=True)
    humidity = Column(Float, nullable=True)
    temperature = Column(Float, nullable=True)
    pressure = Column(Float, nullable=True)
    wind_direction = Column(Float, nullable=True)
    wind_speed = Column(Float, nullable=True)
    wind_gust = Column(Float, nullable=True)
    precipitation_rate = Column(Float, nullable=True)
    precipitation_total = Column(Float, nullable=True)
    request_time = Column(TIMESTAMP(timezone=True), nullable=False, unique=True, index=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=func.now(), index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "solar_radiation": self.solar_radiation,
            "ultraviolet_radiation": self.ultraviolet_radiation,
            "humidity": self.humidity,
            "temperature": self.temperature,
            "pressure": self.pressure,
            "wind_direction": self.wind_direction,
            "wind_speed": self.wind_speed,
            "wind_gust": self.wind_gust,
            "precipitation_rate": self.precipitation_rate,
            "precipitation_total": self.precipitation_total,
            "request_time": self.request_time.isoformat() if self.request_time else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<WeatherLogWunderground id={self.id} temp={self.temperature} humidity={self.humidity}>"


class WeatherLogConsole(db.Model):
    """
    Model untuk menyimpan data cuaca dari Console Station (via POST).
    Data disimpan langsung dalam Imperial units tanpa konversi.
    """
    __tablename__ = "weather_log_console"
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # System info
    runtime = Column(Integer, nullable=True)  # Waktu berjalan console (detik)
    heap = Column(Integer, nullable=True)  # Memory heap
    
    # Indoor sensors
    temperature_indoor = Column(Float, nullable=True)  # tempinf (°F)
    humidity_indoor = Column(Float, nullable=True)  # humidityin (%)
    
    # Barometer
    pressure_relative = Column(Float, nullable=True)  # baromrelin (inHg)
    pressure_absolute = Column(Float, nullable=True)  # baromabsin (inHg)
    
    # Outdoor sensors
    temperature = Column(Float, nullable=True)  # tempf (°F)
    humidity = Column(Float, nullable=True)  # humidity (%)
    
    # Wind
    wind_direction = Column(Float, nullable=True)  # winddir (°)
    wind_speed = Column(Float, nullable=True)  # windspeedmph (mph)
    wind_gust = Column(Float, nullable=True)  # windgustmph (mph)
    max_daily_gust = Column(Float, nullable=True)  # maxdailygust (mph)
    
    # Solar & UV
    solar_radiation = Column(Float, nullable=True)  # solarradiation (W/m²)
    uvi = Column(Float, nullable=True)  # uv
    
    # Rain
    rain_rate = Column(Float, nullable=True)  # rainratein (in/hr)
    rain_event = Column(Float, nullable=True)  # eventrainin (in)
    rain_hourly = Column(Float, nullable=True)  # hourlyrainin (in)
    rain_daily = Column(Float, nullable=True)  # dailyrainin (in)
    rain_weekly = Column(Float, nullable=True)  # weeklyrainin (in)
    rain_monthly = Column(Float, nullable=True)  # monthlyrainin (in)
    rain_yearly = Column(Float, nullable=True)  # yearlyrainin (in)
    rain_total = Column(Float, nullable=True)  # totalrainin (in)
    
    # VPD (Vapor Pressure Deficit)
    vpd = Column(Float, nullable=True)  # vpd (kPa)
    
    # Timestamp dari console station
    date_utc = Column(TIMESTAMP(timezone=True), nullable=True, unique=True, index=True)  # dateutc dari console
    created_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "runtime": self.runtime,
            "heap": self.heap,
            "temperature_indoor": self.temperature_indoor,
            "humidity_indoor": self.humidity_indoor,
            "pressure_relative": self.pressure_relative,
            "pressure_absolute": self.pressure_absolute,
            "temperature": self.temperature,
            "humidity": self.humidity,
            "wind_direction": self.wind_direction,
            "wind_speed": self.wind_speed,
            "wind_gust": self.wind_gust,
            "max_daily_gust": self.max_daily_gust,
            "solar_radiation": self.solar_radiation,
            "uvi": self.uvi,
            "rain_rate": self.rain_rate,
            "rain_event": self.rain_event,
            "rain_hourly": self.rain_hourly,
            "rain_daily": self.rain_daily,
            "rain_weekly": self.rain_weekly,
            "rain_monthly": self.rain_monthly,
            "rain_yearly": self.rain_yearly,
            "rain_total": self.rain_total,
            "vpd": self.vpd,
            "date_utc": self.date_utc.isoformat() if self.date_utc else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<WeatherLogConsole id={self.id} temp={self.temperature} humidity={self.humidity}>"


class WeatherLogEcowitt(db.Model):
    __tablename__ = "weather_log_ecowitt"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vpd_outdoor = Column(Float, nullable=True)
    temperature_main_outdoor = Column(Float, nullable=True)
    temperature_feels_like_outdoor = Column(Float, nullable=True)
    temperature_apparent_outdoor = Column(Float, nullable=True)
    dew_point_outdoor = Column(Float, nullable=True)
    humidity_outdoor = Column(Float, nullable=True)
    temperature_main_indoor = Column(Float, nullable=True)
    temperature_feels_like_indoor = Column(Float, nullable=True)
    temperature_apparent_indoor = Column(Float, nullable=True)
    dew_point_indoor = Column(Float, nullable=True)
    humidity_indoor = Column(Float, nullable=True)
    solar_irradiance = Column(Float, nullable=True)
    uvi = Column(Float, nullable=True)
    rain_rate = Column(Float, nullable=True)
    rain_daily = Column(Float, nullable=True)
    rain_event = Column(Float, nullable=True)
    rain_hour = Column(Float, nullable=True)
    rain_weekly = Column(Float, nullable=True)
    rain_monthly = Column(Float, nullable=True)
    rain_yearly = Column(Float, nullable=True)
    wind_speed = Column(Float, nullable=True)
    wind_gust = Column(Float, nullable=True)
    wind_direction = Column(Float, nullable=True)
    pressure_relative = Column(Float, nullable=True)
    pressure_absolute = Column(Float, nullable=True)
    battery_sensor_array = Column(Float, nullable=True)
    request_time = Column(TIMESTAMP(timezone=True), nullable=False, unique=True, index=True)
    created_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "vpd_outdoor": self.vpd_outdoor,
            "temperature_main_outdoor": self.temperature_main_outdoor,
            "temperature_feels_like_outdoor": self.temperature_feels_like_outdoor,
            "temperature_apparent_outdoor": self.temperature_apparent_outdoor,
            "dew_point_outdoor": self.dew_point_outdoor,
            "humidity_outdoor": self.humidity_outdoor,
            "temperature_main_indoor": self.temperature_main_indoor,
            "temperature_feels_like_indoor": self.temperature_feels_like_indoor,
            "temperature_apparent_indoor": self.temperature_apparent_indoor,
            "dew_point_indoor": self.dew_point_indoor,
            "humidity_indoor": self.humidity_indoor,
            "solar_irradiance": self.solar_irradiance,
            "uvi": self.uvi,
            "rain_rate": self.rain_rate,
            "rain_daily": self.rain_daily,
            "rain_event": self.rain_event,
            "rain_hour": self.rain_hour,
            "rain_weekly": self.rain_weekly,
            "rain_monthly": self.rain_monthly,
            "rain_yearly": self.rain_yearly,
            "wind_speed": self.wind_speed,
            "wind_gust": self.wind_gust,
            "wind_direction": self.wind_direction,
            "pressure_relative": self.pressure_relative,
            "pressure_absolute": self.pressure_absolute,
            "battery_sensor_array": self.battery_sensor_array,
            "request_time": self.request_time.isoformat() if self.request_time else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<WeatherLogEcowitt id={self.id} temp_out={self.temperature_main_outdoor} humidity_out={self.humidity_outdoor}>"


class DataXGBoost(db.Model):
    """
    Tabel untuk menyimpan referensi data weather_log yang digunakan untuk prediksi XGBoost.
    Setiap sumber menggunakan 1 data terbaru (ID tunggal).
    """
    __tablename__ = "data_xgboost"
    id = Column(Integer, primary_key=True, autoincrement=True)
    weather_log_console_id = Column(Integer, ForeignKey('weather_log_console.id'), nullable=True, index=True)
    weather_log_ecowitt_id = Column(Integer, ForeignKey('weather_log_ecowitt.id'), nullable=True, index=True)
    weather_log_wunderground_id = Column(Integer, ForeignKey('weather_log_wunderground.id'), nullable=True, index=True)
    
    # Relationships
    weather_log_console = relationship('WeatherLogConsole', backref='data_xgboost_refs')
    weather_log_ecowitt = relationship('WeatherLogEcowitt', backref='data_xgboost_refs')
    weather_log_wunderground = relationship('WeatherLogWunderground', backref='data_xgboost_refs')

    def to_dict(self):
        return {
            "id": self.id,
            "weather_log_console_id": self.weather_log_console_id,
            "weather_log_ecowitt_id": self.weather_log_ecowitt_id,
            "weather_log_wunderground_id": self.weather_log_wunderground_id,
        }

    def __repr__(self):
        return f"<DataXGBoost id={self.id} console={self.weather_log_console_id} ecowitt={self.weather_log_ecowitt_id} wu={self.weather_log_wunderground_id}>"


class DataLSTM(db.Model):
    """
    Tabel untuk menyimpan referensi data weather_log yang digunakan untuk prediksi LSTM.
    Setiap sumber menggunakan 144 data (JSON array ID).
    """
    __tablename__ = "data_lstm"
    id = Column(Integer, primary_key=True, autoincrement=True)
    weather_log_console_ids = Column(ARRAY(Integer), nullable=True)  # [id1, id2, ..., id144]
    weather_log_ecowitt_ids = Column(ARRAY(Integer), nullable=True)  # [id1, id2, ..., id144]
    weather_log_wunderground_ids = Column(ARRAY(Integer), nullable=True)  # [id1, id2, ..., id144]

    def to_dict(self):
        return {
            "id": self.id,
            "weather_log_console_ids": self.weather_log_console_ids,
            "weather_log_ecowitt_ids": self.weather_log_ecowitt_ids,
            "weather_log_wunderground_ids": self.weather_log_wunderground_ids,
        }

    def __repr__(self):
        return f"<DataLSTM id={self.id}>"


class XGBoostPredictionResult(db.Model):
    """
    Tabel untuk menyimpan hasil prediksi XGBoost (klasifikasi arah hujan).
    Menyimpan hasil prediksi dari 3 sumber: Console, Ecowitt, Wunderground.
    Setiap result adalah FK ke tabel Label (class 0-8).
    """
    __tablename__ = "xgboost_prediction_result"
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # FK ke Label - hasil prediksi class 0-8
    console_result_id = Column(Integer, ForeignKey('label.id'), nullable=True, index=True)
    ecowitt_result_id = Column(Integer, ForeignKey('label.id'), nullable=True, index=True)
    wunderground_result_id = Column(Integer, ForeignKey('label.id'), nullable=True, index=True)
    
    # Relationships ke Label — lazy='joined' karena Label hanya 9 rows dan
    # to_dict() selalu mengakses label.name, menghindari 3 lazy-load queries
    console_label = relationship('Label', foreign_keys=[console_result_id], backref='console_predictions', lazy='joined')
    ecowitt_label = relationship('Label', foreign_keys=[ecowitt_result_id], backref='ecowitt_predictions', lazy='joined')
    wunderground_label = relationship('Label', foreign_keys=[wunderground_result_id], backref='wunderground_predictions', lazy='joined')

    def to_dict(self):
        return {
            "id": self.id,
            "console_result_id": self.console_result_id,
            "ecowitt_result_id": self.ecowitt_result_id,
            "wunderground_result_id": self.wunderground_result_id,
            "console_label": self.console_label.name if self.console_label else None,
            "ecowitt_label": self.ecowitt_label.name if self.ecowitt_label else None,
            "wunderground_label": self.wunderground_label.name if self.wunderground_label else None,
        }

    def __repr__(self):
        return f"<XGBoostPredictionResult id={self.id} console={self.console_result_id} ecowitt={self.ecowitt_result_id} wu={self.wunderground_result_id}>"


class LSTMPredictionResult(db.Model):
    """
    Tabel untuk menyimpan hasil prediksi LSTM (24 jam intensitas hujan).
    Menyimpan hasil prediksi dari 3 sumber: Console, Ecowitt, Wunderground.
    Format JSON berisi array 24 nilai (mm/h).
    """
    __tablename__ = "lstm_prediction_result"
    id = Column(Integer, primary_key=True, autoincrement=True)
    console_result = Column(ARRAY(Float), nullable=True)  # Array 24 nilai (mm/h)
    ecowitt_result = Column(ARRAY(Float), nullable=True)  # Array 24 nilai (mm/h)
    wunderground_result = Column(ARRAY(Float), nullable=True)  # Array 24 nilai (mm/h)

    def to_dict(self):
        return {
            "id": self.id,
            "console_result": self.console_result,
            "ecowitt_result": self.ecowitt_result,
            "wunderground_result": self.wunderground_result,
        }

    def __repr__(self):
        return f"<LSTMPredictionResult id={self.id}>"


class PredictionLog(db.Model):
    """
    Tabel log prediksi yang menyimpan referensi ke:
    - Data weather_log yang digunakan (DataXGBoost, DataLSTM)
    - Hasil prediksi (XGBoostPredictionResult, LSTMPredictionResult)
    - Model yang digunakan
    """
    __tablename__ = "prediction_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign Key ke model
    model_id = Column(Integer, ForeignKey('model.id'), nullable=True, index=True)
    
    # Foreign Keys ke tabel data yang digunakan
    data_xgboost_id = Column(Integer, ForeignKey('data_xgboost.id'), nullable=True, index=True)
    data_lstm_id = Column(Integer, ForeignKey('data_lstm.id'), nullable=True, index=True)
    
    # Foreign Keys ke tabel hasil prediksi
    xgboost_result_id = Column(Integer, ForeignKey('xgboost_prediction_result.id'), nullable=True, index=True)
    lstm_result_id = Column(Integer, ForeignKey('lstm_prediction_result.id'), nullable=True, index=True)
    
    created_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), index=True)
    
    # Composite index untuk query filter model_id + ORDER BY created_at DESC
    __table_args__ = (
        Index('ix_prediction_log_model_created', 'model_id', 'created_at'),
    )
    
    # Relationships
    model = relationship('Model', backref='prediction_logs')
    data_xgboost = relationship('DataXGBoost', backref='prediction_logs')
    data_lstm = relationship('DataLSTM', backref='prediction_logs')
    xgboost_result = relationship('XGBoostPredictionResult', backref='prediction_logs')
    lstm_result = relationship('LSTMPredictionResult', backref='prediction_logs')

    # Property helpers untuk akses weather_log melalui data_xgboost
    @property
    def weather_log_ecowitt(self):
        """Akses weather_log_ecowitt melalui data_xgboost relationship."""
        if self.data_xgboost:
            return self.data_xgboost.weather_log_ecowitt
        return None
    
    @property
    def weather_log_wunderground(self):
        """Akses weather_log_wunderground melalui data_xgboost relationship."""
        if self.data_xgboost:
            return self.data_xgboost.weather_log_wunderground
        return None
    
    @property
    def weather_log_console(self):
        """Akses weather_log_console melalui data_xgboost relationship."""
        if self.data_xgboost:
            return self.data_xgboost.weather_log_console
        return None

    def to_dict(self):
        return {
            "id": self.id,
            "model_id": self.model_id,
            "data_xgboost_id": self.data_xgboost_id,
            "data_lstm_id": self.data_lstm_id,
            "xgboost_result_id": self.xgboost_result_id,
            "lstm_result_id": self.lstm_result_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<PredictionLog id={self.id} model_id={self.model_id} created_at={self.created_at}>"


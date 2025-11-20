from . import db
from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, func
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
    request_time = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), server_default=func.now())

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
    request_time = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now())

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


class PredictionLog(db.Model):
    __tablename__ = "prediction_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    weather_log_wunderground_id = Column(Integer, ForeignKey('weather_log_wunderground.id'), nullable=True)
    weather_log_ecowitt_id = Column(Integer, ForeignKey('weather_log_ecowitt.id'), nullable=True)
    model_id = Column(Integer, ForeignKey('model.id'), nullable=False)
    
    ecowitt_prediction_result = Column(Integer, ForeignKey('label.id'), nullable=True)
    wunderground_prediction_result = Column(Integer, ForeignKey('label.id'), nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now())
    
    weather_log_wunderground = relationship('WeatherLogWunderground', backref='prediction_logs')
    weather_log_ecowitt = relationship('WeatherLogEcowitt', backref='prediction_logs')
    model = relationship('Model', backref='prediction_logs')

    ecowitt_label = relationship('Label', foreign_keys=[ecowitt_prediction_result])
    wunderground_label = relationship('Label', foreign_keys=[wunderground_prediction_result])

    def to_dict(self):
        return {
            "id": self.id,
            "weather_log_wunderground_id": self.weather_log_wunderground_id,
            "weather_log_ecowitt_id": self.weather_log_ecowitt_id,
            "model_id": self.model_id,
            "ecowitt_prediction_result_id": self.ecowitt_prediction_result,
            "wunderground_prediction_result_id": self.wunderground_prediction_result,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<PredictionLog id={self.id} model_id={self.model_id} created_at={self.created_at}>"

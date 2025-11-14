import React, { useState } from 'react';
import axios from 'axios';
import './Auth.css';

const Auth = ({ onLogin }) => {
  const [formData, setFormData] = useState({
    api_key: '',
    api_secret: '',
    password: ''
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const response = await axios.post(
        `/api/auth/login`,
        formData
      );

      if (response.data.success) {
        onLogin(response.data.token);
      } else {
        setError('Помилка входу');
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Помилка підключення до сервера');
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value
    });
  };

  return (
    <div className="auth-container">
      <div className="auth-card">
        <div className="auth-header">
          <h1>🤖 Trinkenbot Enhanced</h1>
          <p>Вхід до системи арбітражної торгівлі</p>
        </div>

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="form-group">
            <label>XT.com API Ключ</label>
            <input
              type="text"
              name="api_key"
              value={formData.api_key}
              onChange={handleChange}
              placeholder="Введіть ваш API ключ XT.com"
              required
            />
          </div>

          <div className="form-group">
            <label>XT.com API Секрет</label>
            <input
              type="password"
              name="api_secret"
              value={formData.api_secret}
              onChange={handleChange}
              placeholder="Введіть ваш API секрет"
              required
            />
          </div>

          <div className="form-group">
            <label>Пароль</label>
            <input
              type="password"
              name="password"
              value={formData.password}
              onChange={handleChange}
              placeholder="Введіть пароль"
              required
            />
          </div>

          {error && <div className="error-message">{error}</div>}

          <button 
            type="submit" 
            className="login-button"
            disabled={loading}
          >
            {loading ? 'Перевірка...' : 'Увійти'}
          </button>
        </form>

        <div className="auth-footer">
          <p>🔒 Безпечний вхід через XT.com API</p>
        </div>
      </div>
    </div>
  );
};

export default Auth;
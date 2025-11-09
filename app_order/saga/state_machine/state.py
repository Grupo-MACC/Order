# state.py
# Esta es una clase base para los estados de la saga y evitar codigo repetido.
# Qué es: Clase base abstracta para todos los estados
# Qué hace: Define la estructura común (__init__, on_event(), __str__())
# que heredan todos los estados

class State(object):
    """
    CLASE BASE: Plantilla para todos los estados
    Cada estado hereda de aquí y define su propio comportamiento.
    
    CONCEPTO:
    - Pending → Estado inicial
    - Paid → Estado cuando pago se acepta
    - NoMoney → Estado cuando pago se rechaza
    - Etc...
    
    Cada estado sabe cómo reaccionar a eventos diferentes.
    """

    def __init__(self):
        """
        Se ejecuta automáticamente cuando se crea una instancia de un estado.
        
        Ej: new_state = Paid()
            → Se llama Paid.__init__()
            → Como Paid no lo define, usa el de State (esta clase)
            → Imprime: "Processing current state: Paid"
        """
        print(f'Processing current state: {str(self)}')
        # str(self) → llama a __str__() → retorna el nombre de la clase

    def on_event(self, event, saga):
        """
        MÉTODO CRUCIAL: Cada estado decide qué hacer con un evento
        
        IMPORTANTE: Esto es una PLANTILLA vacía.
        Cada estado hijo (Pending, Paid, etc) lo sobrescribe con su lógica.
        
        Args:
            event: Diccionario con el evento del broker
            saga: Referencia a la saga para poder ejecutar acciones
                  (publish_payment_command, listen_payment_result, etc)
            
        Returns:
            Un objeto State (puede ser el mismo estado o uno diferente)
        """
        pass  # Esta clase base no hace nada, la heredan y redefinen

    def __repr__(self):
        """Retorna la representación en string del estado."""
        return self.__str__()

    def __str__(self):
        """
        Retorna el NOMBRE de la clase como string.
        
        Ej: si self es una instancia de Paid
            → retorna "Paid"
        """
        return self.__class__.__name__